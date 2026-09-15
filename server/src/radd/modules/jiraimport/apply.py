"""Writing an item draft into Radd (spec 100), or counting what it would write.

ONE code path serves the dry run and the real import: `commit=False` resolves
everything and reports, `commit=True` does the same work and writes. That is what
makes the dry run trustworthy — it cannot disagree with the import, because it IS
the import with the writes turned off.

Every write is ledgered, so rollback can undo it.
"""

from __future__ import annotations

import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth.models import User
from radd.modules.comments import service as comments_service
from radd.modules.comments.schemas import CommentCreate
from radd.modules.comments.types import CommentVisibility
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.notify import service as notify_service
from radd.modules.timelogging import service as timelog_service
from radd.modules.timelogging.schemas import WorklogCreate

from . import ledger
from .transform import ItemDraft
from .types import LedgerEntity, Problem, ProblemKind

def _not_intake():
    """`automations.intake.suppressed()` when that module is loaded, else nothing.

    Deferred and feature-detected, the shape `forms._create_validated` uses:
    `automations` is optional and this module must not stop importing because
    somebody turned it off.
    """
    try:
        from radd.modules.automations import intake as automations_intake
    except ImportError:
        return nullcontext()
    return automations_intake.suppressed()


# Columns a re-import refreshes on an existing item — the before-image rollback
# restores. Deliberately narrow: an import must not be able to undo a change
# somebody made to a column it never touched.
REFRESHED_COLUMNS = (
    "title",
    "description",
    "state_id",
    "priority",
    "assignee_id",
    "reporter_id",
    "type_id",
    "estimate_points",
    "start_date",
    "target_date",
    "updated_at",
)


@dataclass
class Outcome:
    """What happened (or would happen) to one issue."""

    jira_key: str
    radd_key: str = ""
    item_id: uuid.UUID | None = None
    action: str = "create"  # create | update | skip
    reason: str = ""
    comments: int = 0
    worklogs: int = 0
    links: int = 0
    problems: list[Problem] = field(default_factory=list)


async def apply_item(
    session: AsyncSession,
    draft: ItemDraft,
    *,
    actor: User,
    project_id: uuid.UUID,
    project_key: str,
    run_id: uuid.UUID | None,
    commit: bool,
    import_comments: bool,
    import_worklogs: bool,
    seen_comment_ids: set[str],
    seen_worklog_ids: set[str],
) -> Outcome:
    """Create or refresh one item. Never raises — a bad issue is reported and the
    rest of the import continues."""
    radd_key = f"{project_key.upper()}-{draft.number}"
    outcome = Outcome(jira_key=draft.jira_key, radd_key=radd_key)

    if draft.state_id is None:
        status = draft.status_name or "(no status)"
        outcome.action = "skip"
        outcome.reason = f"the Jira status '{status}' has no Radd state"
        outcome.problems.append(
            Problem(
                kind=ProblemKind.ITEM_FAILED,
                message=f"the Jira status '{status}' is not mapped to a Radd state",
                subject=draft.jira_key,
                section="statuses",
                mapping_key=status,
            )
        )
        return outcome

    existing = await items_service.find_item_by_key(session, radd_key)
    outcome.action = "update" if existing is not None else "create"
    if not commit:
        # Dry run: report what the writes WOULD be, without making them.
        outcome.item_id = existing.id if existing else None
        outcome.comments = 0 if existing else len(draft.comments)
        outcome.worklogs = 0 if existing else len(draft.worklogs)
        outcome.links = len(draft.links)
        return outcome

    try:
        if existing is not None:
            if run_id:
                # Captured BEFORE the update, or there is nothing left to restore.
                ledger.updated(
                    session,
                    run_id,
                    LedgerEntity.ITEM,
                    existing.id,
                    ledger.snapshot_of(existing, REFRESHED_COLUMNS),
                    subject=draft.jira_key,
                )
            await items_service.update_item(session, existing.id, _update_of(draft), actor)
            outcome.item_id = existing.id
        else:
            # An import is HISTORY, not intake (spec 119). Validating a
            # five-year-old ticket would refuse exactly the badly-filled-in
            # issues the checks exist to stop being created TODAY, and would
            # skip them one by one with a "problem" nobody can act on.
            # `events.quiet` already says this — but only when the plan asked
            # for quiet, so the skip has to be said in its own right.
            with _not_intake():
                created = await items_service.create_item(
                    session, _create_of(draft, project_id), actor
                )
            outcome.item_id = created.id
            if run_id:
                ledger.created(
                    session, run_id, LedgerEntity.ITEM, created.id, subject=draft.jira_key
                )
    except Exception as exc:  # noqa: BLE001 — one bad issue must not sink the import
        outcome.action = "skip"
        outcome.reason = str(exc)
        outcome.problems.append(
            Problem(
                kind=ProblemKind.ITEM_FAILED,
                message=_explain(str(exc)),
                subject=draft.jira_key,
                detail=str(exc),
                **_blame(str(exc), draft),
            )
        )
        return outcome

    if draft.watcher_ids and outcome.item_id:
        await notify_service.add_watchers(session, outcome.item_id, draft.watcher_ids)
    if import_comments and outcome.item_id:
        outcome.comments = await _comments(
            session, draft, outcome.item_id, actor, run_id, seen_comment_ids
        )
    if import_worklogs and outcome.item_id:
        outcome.worklogs = await _worklogs(
            session, draft, outcome.item_id, run_id, seen_worklog_ids, outcome
        )
    return outcome


def _explain(error: str) -> str:
    """A service error in the words of the mapping that caused it.

    "unknown field" and "must be a list drawn from […]" are accurate but they
    describe Radd's validator, not the decision you would change.
    """
    lowered = error.lower()
    if "unknown field" in lowered:
        return "a mapped custom field is not usable in this project"
    if "must be a list drawn from" in lowered or "not a valid option" in lowered:
        return "a value is outside the target field's option set"
    if "parent" in lowered and "kind" in lowered:
        return "the parent does not fit Radd's epic ← issue ← subtask hierarchy"
    return "the issue could not be written"


def _blame(error: str, draft: ItemDraft) -> dict[str, str]:
    """Point at the mapping tab (and row) that would fix this error."""
    lowered = error.lower()
    if "unknown field" in lowered or "must be a list drawn from" in lowered:
        # Radd prefixes the failing key: "site: unknown field".
        return {"section": "fields", "mapping_key": error.split(":", 1)[0].strip()}
    if "parent" in lowered:
        return {"section": "issue_types", "mapping_key": draft.type_name}
    return {}


def _create_of(draft: ItemDraft, project_id: uuid.UUID) -> ItemCreate:
    return ItemCreate(
        project_id=project_id,
        number=draft.number,  # Jira's own number, preserved 1:1
        title=draft.title,
        description=draft.description,
        kind=draft.kind,
        type_id=draft.type_id,
        state_id=draft.state_id,
        priority=draft.priority,
        assignee_id=draft.assignee_id,
        reporter_id=draft.reporter_id,
        labels=draft.labels,
        custom_fields=draft.custom_fields,
        estimate_points=draft.estimate_points,
        start_date=_as_date(draft.start_date),
        target_date=_as_date(draft.target_date),
        # Honoured only for an actor holding project.manage — the dry run checks
        # that up front rather than letting fidelity be lost in silence.
        created_at=_as_datetime(draft.created),
        updated_at=_as_datetime(draft.updated or draft.created),
    )


def _update_of(draft: ItemDraft) -> ItemUpdate:
    """A refresh never CLEARS a relation the import could not resolve — an
    unmatched assignee must not wipe one somebody set by hand."""
    patch: dict = {
        "title": draft.title,
        "description": draft.description,
        "state_id": draft.state_id,
        "priority": draft.priority,
        "labels": draft.labels,
        "custom_fields": draft.custom_fields,
        "updated_at": _as_datetime(draft.updated or draft.created),
    }
    for key, value in (
        ("assignee_id", draft.assignee_id),
        ("reporter_id", draft.reporter_id),
        ("type_id", draft.type_id),
        ("estimate_points", draft.estimate_points),
        ("start_date", _as_date(draft.start_date)),
        ("target_date", _as_date(draft.target_date)),
    ):
        if value is not None:
            patch[key] = value
    return ItemUpdate(**patch)


async def _comments(
    session: AsyncSession,
    draft: ItemDraft,
    item_id: uuid.UUID,
    actor: User,
    run_id: uuid.UUID | None,
    seen: set[str],
) -> int:
    """Comments, deduplicated by Jira's own comment id.

    Spec 90 could not do this — it stored no Jira ids, so a re-import would have
    duplicated every comment, and its answer was to skip comments on re-import
    entirely (silently leaving them stale forever).
    """
    written = 0
    for comment in draft.comments:
        if comment.jira_id and comment.jira_id in seen:
            continue
        try:
            created = await comments_service.create_comment(
                session,
                item_id,
                CommentCreate(
                    body=comment.body,
                    author_id=comment.author_id,
                    created_at=_as_datetime(comment.created),
                    # RADD-1180. A Jira internal note imported as a public comment
                    # is a leak, and on a public project a published one.
                    visibility=(
                        CommentVisibility.INTERNAL
                        if comment.internal
                        else CommentVisibility.PUBLIC
                    ),
                ),
                actor,
            )
            if run_id:
                ledger.created(
                    session,
                    run_id,
                    LedgerEntity.COMMENT,
                    created.id,
                    subject=f"{draft.jira_key}#{comment.jira_id}",
                )
            if comment.jira_id:
                seen.add(comment.jira_id)
            written += 1
        except Exception:  # noqa: BLE001 — a bad comment must not lose the issue
            continue
    return written


async def _worklogs(
    session: AsyncSession,
    draft: ItemDraft,
    item_id: uuid.UUID,
    run_id: uuid.UUID | None,
    seen: set[str],
    outcome: Outcome,
) -> int:
    written = 0
    for worklog in draft.worklogs:
        if worklog.jira_id and worklog.jira_id in seen:
            continue
        if worklog.author_id is None:
            # A worklog credits someone with hours. Attributing it to the wrong
            # person is worse than not importing it, so say so instead.
            outcome.problems.append(
                Problem(
                    kind=ProblemKind.WORKLOG_FAILED,
                    message="a worklog's author is unresolved — the hours were not imported",
                    subject=draft.jira_key,
                    section="users",
                )
            )
            continue
        try:
            created = await timelog_service.create_worklog(
                session,
                item_id,
                WorklogCreate(
                    time_spent=worklog.time_spent,
                    worked_on=_as_date(worklog.worked_on),
                    note=worklog.note,
                    author_id=worklog.author_id,
                ),
                author_id=worklog.author_id,
                today=date.today(),
                created_at=_as_datetime(worklog.created),
            )
            if run_id:
                ledger.created(
                    session,
                    run_id,
                    LedgerEntity.WORKLOG,
                    created.id,
                    subject=f"{draft.jira_key}#{worklog.jira_id}",
                )
            if worklog.jira_id:
                seen.add(worklog.jira_id)
            written += 1
        except Exception as exc:  # noqa: BLE001
            outcome.problems.append(
                Problem(
                    kind=ProblemKind.WORKLOG_FAILED,
                    message="a worklog could not be imported",
                    subject=draft.jira_key,
                    detail=str(exc),
                )
            )
    return written


def _as_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _as_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:19])
    except ValueError:
        return None
