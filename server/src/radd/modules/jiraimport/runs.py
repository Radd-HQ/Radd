"""Executing a plan over a snapshot (spec 100) — dry run, import, rollback.

ONE pipeline, one `commit` flag. The dry run resolves everything and writes
nothing; the import does identical work and writes. They cannot disagree about
what would happen, because they are the same code.

Stage order is what makes links work: ITEMS first with Jira numbers preserved, so
every key is addressable, then PARENTS and LINKS once every issue exists, then
the rest. Nothing here touches Jira — it all reads the cache.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import SessionLocal
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.cycles import service as cycles_service
from radd.modules.cycles.schemas import CycleCreate
from radd.modules.events import service as events
from radd.modules.fields import service as fields_service
from radd.modules.fields.types import FieldType
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemLinkCreate, ItemUpdate
from radd.modules.releases import service as releases_service
from radd.modules.releases.schemas import ReleaseCreate
from radd.clock import utcnow

from . import apply, connections, ledger, provision, relink, transform
from .client import browse_url
from .models import JiraConnection, JiraPlan, JiraRun, JiraSnapshot
from .plan import service as plan_service
from .snapshot import store
from .types import (
    TERMINAL_RUN_STAGES,
    JiraCreds,
    LedgerEntity,
    PendingRefKind,
    Problem,
    ProblemKind,
    RunStage,
    SnapshotCatalog,
)

logger = logging.getLogger(__name__)

MAX_RECORDED_PROBLEMS = 1000
COMMIT_EVERY = 50  # issues per transaction — live progress without a huge txn



def _bump(run: JiraRun, key: str, by: int = 1) -> None:
    counts = dict(run.counts or {})
    counts[key] = counts.get(key, 0) + by
    run.counts = counts


def _problem(run: JiraRun, problem: Problem) -> None:
    _bump(run, "problems")
    existing = list(run.problems or [])
    if len(existing) < MAX_RECORDED_PROBLEMS:
        run.problems = [*existing, problem.as_dict()]


async def _canceled(session: AsyncSession, run: JiraRun) -> bool:
    await session.refresh(run, ["stage"])
    return RunStage(run.stage) is RunStage.CANCELED


# --- the pipeline -------------------------------------------------------------


async def execute(run_id: uuid.UUID) -> None:
    """Run one plan to completion in its own session. Never raises."""
    async with SessionLocal() as session:
        run = await session.get(JiraRun, run_id)
        if run is None:
            return
        actor = await session.get(User, run.actor_id) if run.actor_id else None
        plan = await session.get(JiraPlan, run.plan_id) if run.plan_id else None
        snapshot = (
            await session.get(JiraSnapshot, run.snapshot_id) if run.snapshot_id else None
        )
        if actor is None or plan is None or snapshot is None:
            await _fail(session, run_id, "the plan, snapshot or actor no longer exists")
            return
        run.started_at = utcnow()
        await session.commit()

        options = plan_service.options(plan)
        try:
            # Imported work must not notify anyone or fire automation rules. The
            # scope is inherited by everything this task awaits.
            with events.quiet(options.quiet and not run.dry_run):
                await _pipeline(session, run, plan, snapshot, actor)
        except Exception as exc:  # noqa: BLE001 — the job must never crash the process
            logger.exception("jira run %s failed", run_id)
            await _fail(session, run_id, f"unexpected error: {exc}")
            return

        fresh = await session.get(JiraRun, run_id)
        if fresh is not None and RunStage(fresh.stage) not in TERMINAL_RUN_STAGES:
            fresh.stage = RunStage.DONE.value
            fresh.finished_at = utcnow()
            await session.commit()


async def _pipeline(
    session: AsyncSession,
    run: JiraRun,
    plan: JiraPlan,
    snapshot: JiraSnapshot,
    actor: User,
) -> None:
    mappings = plan_service.mappings(plan)
    options = plan_service.options(plan)
    commit = not run.dry_run

    # Timestamp and authorship fidelity is gated on project.manage, and spec 90
    # let it be lost SILENTLY when the actor lacked it. Say so instead.
    await _check_fidelity(session, run, actor)

    run.stage = RunStage.PROVISION.value
    await session.commit()
    connection = (
        await session.get(JiraConnection, snapshot.connection_id)
        if snapshot.connection_id
        else None
    )
    domain = (
        options.placeholder_email_domain
        or (connections.placeholder_email_domain(connection) if connection else "")
    )
    provisioned = await provision.run(
        session,
        plan,
        mappings,
        run_id=run.id if commit else None,
        placeholder_domain=domain,
        commit=commit,
    )
    for problem in provisioned.problems:
        _problem(run, problem)
    for key, value in provisioned.created.items():
        _bump(run, f"{key}_created", value)
    if commit and provisioned.project_id is not None:
        plan.radd_project_id = provisioned.project_id
        plan.provisioned_at = utcnow()
        run.project_id = provisioned.project_id
    await session.commit()

    if provisioned.project_id is None and commit:
        await _fail(session, run.id, "the target project could not be created")
        return

    definitions = await fields_service.list_fields(session)
    catalog_types = {d.key: FieldType(d.type) for d in definitions}
    vocab = transform.Vocab.of(
        mappings,
        state_ids=provisioned.state_ids,
        type_ids=provisioned.type_ids,
        user_ids=provisioned.user_ids,
        team_ids=provisioned.team_ids,
        sprint_field_ids=_sprint_fields(snapshot),
        epic_link_field_id=_epic_field(snapshot),
        # So a value the target select will not accept is dropped from the field
        # rather than costing the whole issue.
        field_options={
            d.key: frozenset(d.options) for d in definitions if d.options
        },
    )
    cycles = await _cycles(session, run, mappings, commit)
    releases = await _releases(session, run, mappings, provisioned.project_id, commit)

    # --- items ---
    run.stage = RunStage.ITEMS.value
    await session.commit()
    key_map: dict[str, str] = {}
    item_ids: dict[str, uuid.UUID] = {}
    parents: dict[str, str] = {}
    links: list[tuple[str, transform.LinkDraft]] = []
    report_rows: list[dict] = []
    # Dedupe across RUNS, not just within one: the ledger is the record of which
    # Jira comment/worklog ids this importer has already written, so a re-import
    # recognises them instead of duplicating. Spec 90 stored no ids at all, so its
    # only defence was to skip comments on a re-import entirely.
    seen_comments = await _already_imported(session, plan.id, LedgerEntity.COMMENT)
    seen_worklogs = await _already_imported(session, plan.id, LedgerEntity.WORKLOG)
    processed = 0

    async for row in store.iter_issues(session, snapshot.id):
        if await _canceled(session, run):
            return
        draft = transform.build(row.payload, mappings, vocab, catalog_types)
        outcome = await apply.apply_item(
            session,
            draft,
            actor=actor,
            project_id=provisioned.project_id or uuid.uuid4(),
            project_key=plan.radd_project_key,
            run_id=run.id if commit else None,
            commit=commit,
            import_comments=options.import_comments,
            import_worklogs=options.import_worklogs,
            seen_comment_ids=seen_comments,
            seen_worklog_ids=seen_worklogs,
        )
        key_map[draft.jira_key] = outcome.radd_key
        for problem in outcome.problems:
            _problem(run, problem)
        _bump(run, {"create": "items", "update": "items_updated"}.get(outcome.action, "skipped"))
        _bump(run, "comments", outcome.comments)
        _bump(run, "worklogs", outcome.worklogs)
        for field_key, value in draft.dropped:
            _bump(run, "values_dropped")
            _problem(
                run,
                Problem(
                    kind=ProblemKind.VALUE_DROPPED,
                    message=(
                        f"'{value}' is not an option on the '{field_key}' field, so it was "
                        "dropped — add the option, or map the value to one that exists"
                    ),
                    subject=draft.jira_key,
                    section="fields",
                    mapping_key=field_key,
                ),
            )
        if outcome.item_id is not None:
            item_ids[draft.jira_key] = outcome.item_id
            if parent := (draft.parent_jira_key or draft.epic_jira_key):
                parents[draft.jira_key] = parent.upper()
            links.extend((draft.jira_key, link) for link in draft.links)
            if commit:
                await _attach_cycle_release(session, draft, outcome.item_id, cycles, releases, actor)
        if run.dry_run and len(report_rows) < 500:
            report_rows.append(
                {
                    "jira_key": draft.jira_key,
                    "radd_key": outcome.radd_key,
                    "action": outcome.action,
                    "reason": outcome.reason,
                    "title": draft.title[:120],
                    "comments": outcome.comments,
                    "worklogs": len(draft.worklogs),
                    "links": len(draft.links),
                }
            )
        processed += 1
        if processed % COMMIT_EVERY == 0:
            await session.commit()
    await session.commit()

    if run.dry_run:
        run.report = {
            "rows": report_rows,
            "truncated": processed > len(report_rows),
            "would_provision": provisioned.created,
        }

    # --- parents, then links: only once every issue exists ---
    run.stage = RunStage.PARENTS.value
    await session.commit()
    creds = connections.creds_of(connection) if connection else None
    await _parents(session, run, parents, item_ids, key_map, actor, creds, commit)
    await session.commit()

    run.stage = RunStage.LINKS.value
    await session.commit()
    await _links(session, run, links, item_ids, key_map, actor, creds, commit)
    await session.commit()

    # --- relink anything that just became importable ---
    if commit:
        run.stage = RunStage.RELINK.value
        await session.commit()
        result = await relink.resolve_all(session, actor, key_map=key_map)
        _bump(run, "relinked", result.resolved)
        _bump(run, "still_pending", result.still_pending)
        for prefix, count in result.pending_by_project.items():
            _problem(
                run,
                Problem(
                    kind=ProblemKind.LINK_UNRESOLVED,
                    message=f"still waiting for {prefix}-* to be imported",
                    subject=f"{count} reference(s)",
                ),
            )
        await session.commit()


async def _already_imported(
    session: AsyncSession, plan_id: uuid.UUID, entity: LedgerEntity
) -> set[str]:
    """Jira ids this plan's earlier runs already wrote, from the ledger subjects
    (`<JIRA-KEY>#<jira id>`)."""
    from sqlalchemy import select

    from .models import JiraImportRecord

    result = await session.execute(
        select(JiraImportRecord.subject)
        .join(JiraRun, JiraRun.id == JiraImportRecord.run_id)
        .where(JiraRun.plan_id == plan_id, JiraImportRecord.entity_type == entity.value)
    )
    return {
        subject.rpartition("#")[2]
        for subject in result.scalars()
        if subject and "#" in subject
    }


async def _check_fidelity(session: AsyncSession, run: JiraRun, actor: User) -> None:
    """Preserved timestamps and real authorship need `project.manage`. Without it
    the services IGNORE those fields rather than refusing, so an import would
    quietly stamp 45,000 issues with today's date and credit them to the importer."""
    permissions = await authz.effective_permissions(session, actor)
    if Permission.PROJECT_MANAGE not in permissions:
        _problem(
            run,
            Problem(
                kind=ProblemKind.PERMISSION,
                message=(
                    "you lack project.manage, so original dates and authorship CANNOT be "
                    "preserved — every issue would be stamped with today and credited to you"
                ),
                subject=actor.email,
            ),
        )


def _sprint_fields(snapshot: JiraSnapshot) -> tuple[str, ...]:
    from . import schemakeys

    return tuple(
        schemakeys.find_by_schema_key(
            store.catalog(snapshot, SnapshotCatalog.FIELDS), schemakeys.JiraSchemaKey.SPRINT
        )
    )


def _epic_field(snapshot: JiraSnapshot) -> str:
    from . import schemakeys

    catalog = store.catalog(snapshot, SnapshotCatalog.FIELDS)
    found = schemakeys.find_by_schema_key(catalog, schemakeys.JiraSchemaKey.EPIC_LINK)
    if found:
        return found[0]
    return next(
        (fid for fid, meta in catalog.items() if (meta.get("name") or "").lower() == "epic link"),
        "",
    )


async def _cycles(
    session: AsyncSession, run: JiraRun, mappings, commit: bool
) -> dict[str, uuid.UUID]:
    """Sprints → cycles, carrying dates and completion so a CLOSED sprint imports
    as a completed cycle rather than a dateless draft."""
    out: dict[str, uuid.UUID] = {}
    existing = {c.name.strip().lower(): c.id for c in await cycles_service.list_cycles(session)}
    for entry in mappings.sprints:
        from .types import VocabAction

        if entry.action is VocabAction.IGNORE:
            continue
        if entry.cycle_id is not None:
            out[entry.jira] = entry.cycle_id
            continue
        if (found := existing.get(entry.jira.strip().lower())) is not None:
            out[entry.jira] = found
            continue
        if not commit:
            _bump(run, "cycles_created")
            continue
        try:
            created = await cycles_service.create_cycle(
                session,
                CycleCreate(
                    name=entry.jira[:200],
                    start_date=_as_date(entry.start_date),
                    end_date=_as_date(entry.end_date),
                ),
                today=utcnow().date(),
            )
            await session.flush()
            if entry.complete_date and (stamp := _as_datetime(entry.complete_date)):
                created_row = await cycles_service.get_cycle(session, created.id)
                created_row.completed_at = stamp
            ledger.created(session, run.id, LedgerEntity.CYCLE, created.id, subject=entry.jira)
            existing[entry.jira.strip().lower()] = created.id
            out[entry.jira] = created.id
            _bump(run, "cycles_created")
        except Exception as exc:  # noqa: BLE001
            _problem(
                run,
                Problem(
                    kind=ProblemKind.PROVISION_FAILED,
                    message="a sprint could not become a cycle",
                    subject=entry.jira,
                    detail=str(exc),
                ),
            )
    return out


async def _releases(
    session: AsyncSession, run: JiraRun, mappings, project_id: uuid.UUID | None, commit: bool
) -> dict[str, uuid.UUID]:
    """Fix versions → releases. Not imported at all before spec 100."""
    out: dict[str, uuid.UUID] = {}
    if project_id is None:
        return out
    from .types import VocabAction

    existing = {
        r.version.strip().lower(): r.id
        for r in await releases_service.list_releases(session, project_id)
    }
    for entry in mappings.versions:
        if entry.action is VocabAction.IGNORE:
            continue
        if entry.release_id is not None:
            out[entry.jira] = entry.release_id
            continue
        if (found := existing.get(entry.jira.strip().lower())) is not None:
            out[entry.jira] = found
            continue
        if not commit:
            _bump(run, "releases_created")
            continue
        try:
            created = await releases_service.create_release(
                session,
                ReleaseCreate(
                    project_id=project_id, name=entry.jira[:200], version=entry.jira[:100]
                ),
            )
            await session.flush()
            ledger.created(session, run.id, LedgerEntity.RELEASE, created.id, subject=entry.jira)
            existing[entry.jira.strip().lower()] = created.id
            out[entry.jira] = created.id
            _bump(run, "releases_created")
        except Exception as exc:  # noqa: BLE001
            _problem(
                run,
                Problem(
                    kind=ProblemKind.PROVISION_FAILED,
                    message="a fix version could not become a release",
                    subject=entry.jira,
                    detail=str(exc),
                ),
            )
    return out


async def _attach_cycle_release(
    session: AsyncSession,
    draft: transform.ItemDraft,
    item_id: uuid.UUID,
    cycles: dict[str, uuid.UUID],
    releases: dict[str, uuid.UUID],
    actor: User,
) -> None:
    """The LAST sprint an issue was in is its current cycle (Jira lists them in
    order); the first mapped fix version is its release."""
    patch: dict = {}
    for name in reversed(draft.sprint_names):
        if (cycle_id := cycles.get(name)) is not None:
            patch["cycle_id"] = cycle_id
            break
    for name in draft.version_names:
        if (release_id := releases.get(name)) is not None:
            patch["release_id"] = release_id
            break
    if patch:
        try:
            await items_service.update_item(session, item_id, ItemUpdate(**patch), actor)
        except Exception:  # noqa: BLE001 — a cycle is not worth losing the issue over
            pass


async def _parents(
    session: AsyncSession,
    run: JiraRun,
    parents: dict[str, str],
    item_ids: dict[str, uuid.UUID],
    key_map: dict[str, str],
    actor: User,
    creds: JiraCreds | None,
    commit: bool,
) -> None:
    for child_key, parent_key in parents.items():
        child_id = item_ids.get(child_key)
        if child_id is None:
            continue
        target = await _resolve(session, parent_key, key_map)
        if target is None:
            _bump(run, "parents_pending")
            if commit and creds:
                await relink.record(
                    session,
                    run_id=run.id,
                    actor=actor,
                    source_item_id=child_id,
                    kind=PendingRefKind.PARENT,
                    target_jira_key=parent_key,
                    browse_url=browse_url(creds, parent_key),
                )
            continue
        if not commit:
            _bump(run, "parents_linked")
            continue
        try:
            await items_service.update_item(
                session, child_id, ItemUpdate(parent_id=target), actor
            )
            _bump(run, "parents_linked")
        except Exception as exc:  # noqa: BLE001
            # Radd's epic ← issue ← subtask ladder is stricter than Jira's, so a
            # legal Jira parent can be an illegal Radd one. Keep the reference
            # visible as a web link rather than losing it.
            _bump(run, "parents_incompatible")
            _problem(
                run,
                Problem(
                    kind=ProblemKind.PARENT_INCOMPATIBLE,
                    message=(
                        "the parent does not fit Radd's epic ← issue ← subtask hierarchy — "
                        "check which level each Jira issue type maps to"
                    ),
                    subject=f"{child_key} → {parent_key}",
                    detail=str(exc),
                    section="issue_types",
                ),
            )
            if creds:
                await relink.record(
                    session,
                    run_id=run.id,
                    actor=actor,
                    source_item_id=child_id,
                    kind=PendingRefKind.PARENT,
                    target_jira_key=parent_key,
                    browse_url=browse_url(creds, parent_key),
                )


async def _links(
    session: AsyncSession,
    run: JiraRun,
    links: list[tuple[str, transform.LinkDraft]],
    item_ids: dict[str, uuid.UUID],
    key_map: dict[str, str],
    actor: User,
    creds: JiraCreds | None,
    commit: bool,
) -> None:
    for source_key, link in links:
        source_id = item_ids.get(source_key)
        if source_id is None:
            continue
        target = await _resolve(session, link.target_jira_key, key_map)
        if target is None:
            _bump(run, "links_pending")
            if commit and creds:
                await relink.record(
                    session,
                    run_id=run.id,
                    actor=actor,
                    source_item_id=source_id,
                    kind=PendingRefKind.LINK,
                    target_jira_key=link.target_jira_key,
                    browse_url=browse_url(creds, link.target_jira_key),
                    link_type=link.link_type,
                    inward=link.inward,
                )
            continue
        if not commit:
            _bump(run, "links")
            continue
        if target == source_id:
            continue
        source, other = (target, source_id) if link.inward else (source_id, target)
        try:
            created = await items_service.add_item_link(
                session,
                source,
                ItemLinkCreate(target_id=other, link_type=link.link_type),
                actor,
            )
            if created is not None:
                ledger.created(
                    session,
                    run.id,
                    LedgerEntity.ITEM_LINK,
                    getattr(created, "id", created),
                    subject=f"{source_key} → {link.target_jira_key}",
                )
            _bump(run, "links")
        except Exception:  # noqa: BLE001 — a duplicate/symmetric mirror is fine
            _bump(run, "links_skipped")


async def _resolve(
    session: AsyncSession, jira_key: str, key_map: dict[str, str]
) -> uuid.UUID | None:
    """This run's imports first, then the WHOLE database — so a target that lives
    in a PRIOR import or another project still resolves."""
    radd_key = key_map.get(jira_key, jira_key)
    found = await items_service.find_item_by_key(session, radd_key)
    if found is None and radd_key != jira_key:
        found = await items_service.find_item_by_key(session, jira_key)
    return found.id if found else None


def _as_date(raw: str):
    from datetime import date

    try:
        return date.fromisoformat(raw[:10]) if raw else None
    except ValueError:
        return None


def _as_datetime(raw: str):
    try:
        return datetime.fromisoformat(raw[:19]) if raw else None
    except ValueError:
        return None


async def _fail(session: AsyncSession, run_id: uuid.UUID, message: str) -> None:
    """Rolling back FIRST: a failure mid-page poisons the session, and then the
    commit recording the failure raises too — which is how spec 90 left runs
    stuck mid-flight until the next restart."""
    await session.rollback()
    run = await session.get(JiraRun, run_id)
    if run is None:
        return
    _problem(run, Problem(kind=ProblemKind.ITEM_FAILED, message=message))
    run.stage = RunStage.FAILED.value
    run.finished_at = utcnow()
    await session.commit()


def start(run_id: uuid.UUID) -> None:
    asyncio.create_task(execute(run_id))  # noqa: RUF006 — tracked by the run row


async def mark_interrupted() -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(JiraRun)
            .where(
                JiraRun.finished_at.is_(None),
                JiraRun.stage.not_in([s.value for s in TERMINAL_RUN_STAGES]),
            )
            .values(stage=RunStage.FAILED.value, finished_at=utcnow())
        )
        await session.commit()
