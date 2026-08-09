"""The import run (spec 117, RADD-1018).

Provision, write, record, reverse. The stage order carries two decisions worth
naming: BODIES follows PAGES because a link can only be rewritten once its
target's Radd id exists, and ATTACHMENTS precedes COMMENTS because a comment can
embed an image.

The whole pipeline runs inside `events.quiet`, so notify, webhooks and automations
skip the import while search and history still consume it.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from datetime import UTC, datetime

from fastapi import UploadFile
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import SessionLocal
from radd.modules.attachments import service as attachments_service
from radd.modules.auth.models import User
from radd.modules.comments import service as comments_service
from radd.modules.comments.schemas import CommentCreate
from radd.modules.events import service as events
from radd.modules.pages import labels as page_labels, spaces as page_spaces
from radd.modules.pages.schemas import PageSpaceCreate

from . import apply as apply_page, ledger, plan as plan_service, restrictions
from .apply import IMPORT_PERMISSIONS
from .ledger import LedgerEntity
from .models import ConfluenceRun, ConfluenceSnapshot, ConfluenceSnapshotPage
from .schemas import GroupMapping
from .snapshot import service as snapshot_service, store
from .storage import ConvertContext
from .types import (
    ConfluenceEntity,
    JiraLinkAction,
    Problem,
    ProblemKind,
    RunKind,
    RunStage,
    SpaceAction,
    TERMINAL_RUN_STAGES,
    UpsertAction,
)

logger = logging.getLogger(__name__)

COMMIT_EVERY = 25
MAX_RECORDED_PROBLEMS = 1000
MAX_REPORT_ROWS = 500


def _bump(run: ConfluenceRun, key: str, by: int = 1) -> None:
    counts = dict(run.counts or {})
    counts[key] = counts.get(key, 0) + by
    run.counts = counts


def _problem(run: ConfluenceRun, problem: Problem) -> None:
    problems = list(run.problems or [])
    if len(problems) < MAX_RECORDED_PROBLEMS:
        problems.append(problem.as_dict())
        run.problems = problems
    _bump(run, "problems")


async def _canceled(session: AsyncSession, run: ConfluenceRun) -> bool:
    await session.refresh(run, ["stage"])
    return RunStage(run.stage) is RunStage.CANCELED


async def _stage(session: AsyncSession, run: ConfluenceRun, stage: RunStage) -> None:
    run.stage = stage.value
    await session.commit()


# --- the run ------------------------------------------------------------------


async def execute(run_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        run = await session.get(ConfluenceRun, run_id)
        if run is None:
            return
        run.started_at = datetime.now(UTC).replace(tzinfo=None)
        options = plan_service.PlanOptions.model_validate(
            (run.plan_snapshot or {}).get("options") or {}
        )
        try:
            # Silent: outward-acting consumers skip the import, search and history
            # do not. A dry run is never quiet-scoped, because it writes nothing.
            with events.quiet(options.quiet and not run.dry_run):
                await _pipeline(session, run)
        except Exception as exc:  # noqa: BLE001 — the row is the only reporter
            logger.exception("confluence run %s failed", run_id)
            await _fail(session, run_id, f"unexpected error: {exc}")


async def _pipeline(session: AsyncSession, run: ConfluenceRun) -> None:
    commit = not run.dry_run
    run_id = run.id if commit else None
    plan_snapshot = run.plan_snapshot or {}
    mappings = plan_service.PlanMappings.model_validate(plan_snapshot.get("mappings") or {})
    options = plan_service.PlanOptions.model_validate(plan_snapshot.get("options") or {})
    snapshot = await snapshot_service.require_complete(session, run.snapshot_id)
    actor_id = run.actor_id or (await _any_admin(session))

    await _stage(session, run, RunStage.PROVISION)
    people = await _people(session, mappings)
    space_ids = await _spaces(session, run, snapshot, mappings, actor_id, run_id, commit)
    if await _canceled(session, run):
        return

    await _stage(session, run, RunStage.PAGES)
    rows = await store.pages(session, snapshot.id)
    overrides = {g.name: g for g in mappings.groups}
    jira_projects = {
        j.project_key for j in mappings.jira_links if j.action is JiraLinkAction.RESOLVE
    }

    # Resolved as pages land, so a link to a page created earlier in this same run
    # already works. Everything still unresolved becomes a pending ref.
    by_external: dict[str, uuid.UUID] = {}
    by_title: dict[str, uuid.UUID] = {}
    attachments_by_page: dict[str, dict[str, str]] = {}
    report_rows: list[dict] = []

    for index, row in enumerate(rows):
        if index % COMMIT_EVERY == 0:
            await session.commit()
            if await _canceled(session, run):
                return
        space_id = space_ids.get(row.space_key)
        if space_id is None:
            _bump(run, "pages_skipped")
            continue

        # Restrictions FIRST, because an unresolvable principal must stop the page
        # from being created at all — writing it and closing it afterwards leaves a
        # window, and a failure between the two leaves it open forever.
        resolution = None
        if options.import_restrictions and row.restrictions:
            resolution = await restrictions.resolve(
                session, row.restrictions, options=options,
                overrides=overrides, page_title=row.title,
            )
            for problem in resolution.problems:
                _problem(run, problem)
            if resolution.blocked:
                _bump(run, "pages_blocked")
                continue

        context = _context(
            snapshot, by_external, by_title, attachments_by_page.get(row.page_id, {}),
            jira_projects, people,
        )
        parent_id = _nearest_imported(row, by_external)
        outcome = await apply_page.upsert_page(
            session,
            space_id=space_id,
            parent_id=parent_id,
            title=row.title,
            body_storage=row.body,
            position=float(row.position or 0),
            external_source=snapshot.external_source,
            external_id=row.page_id,
            author_id=people.get(_author_of(row), actor_id),
            created_at=_parsed((row.payload or {}).get("history", {}).get("createdDate", "")),
            updated_at=_parsed(((row.payload or {}).get("version") or {}).get("when", "")),
            context=context,
            actor_id=actor_id,
            run_id=run_id,
            commit=commit,
        )
        for problem in outcome.problems:
            _problem(run, problem)
        _bump(
            run,
            "pages_created"
            if outcome.action is UpsertAction.CREATE
            else "pages_updated",
        )
        if outcome.page_id is not None:
            by_external[row.page_id] = outcome.page_id
            by_title[row.title] = outcome.page_id
            if commit and resolution is not None:
                written = await restrictions.apply(
                    session, outcome.page_id, resolution, actor_id=actor_id
                )
                for _ in range(written):
                    await ledger.created(
                        session, run_id, LedgerEntity.GRANT, outcome.page_id, subject=row.title
                    )
                _bump(run, "restrictions", written)
            if commit and row.labels:
                await page_labels.set_labels(session, outcome.page_id, list(row.labels), actor_id)
                _bump(run, "labels", len(row.labels))
        if len(report_rows) < MAX_REPORT_ROWS:
            report_rows.append({
                "title": row.title, "space": row.space_key,
                "action": outcome.action.value, "problems": len(outcome.problems),
            })
    await session.commit()

    if options.import_attachments:
        await _stage(session, run, RunStage.ATTACHMENTS)
        attachments_by_page = await _attachments(
            session, run, snapshot, by_external, actor_id, run_id, commit
        )
        # The bodies were converted before their attachments existed, so any page
        # that referenced one is converted again now that the URLs are real. Cheap:
        # the raw body is cached, so this is a re-convert, not a re-download.
        await _stage(session, run, RunStage.BODIES)
        await _reconvert(
            session, run, snapshot, rows, by_external, by_title,
            attachments_by_page, jira_projects, people, actor_id, run_id, commit,
        )

    if options.import_comments:
        await _stage(session, run, RunStage.COMMENTS)
        await _comments(session, run, snapshot, rows, by_external, people, actor_id, commit)

    if options.include_history and snapshot.include_history:
        await _stage(session, run, RunStage.VERSIONS)
        await _history(session, run, rows, by_external, people, actor_id, run_id, commit)

    await _stage(session, run, RunStage.RELINK)
    if commit:
        from radd.modules.pages import backlinks, mentions as page_mentions

        # Derived indexes only exist for content that went through the save path.
        await backlinks.reindex_all(session)
        await page_mentions.reindex_all(session)
        await session.commit()

    run.report = {"rows": report_rows, "truncated": len(rows) > MAX_REPORT_ROWS}
    run.stage = RunStage.DONE.value
    run.finished_at = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()


def _context(
    snapshot: ConfluenceSnapshot,
    by_external: dict[str, uuid.UUID],
    by_title: dict[str, uuid.UUID],
    attachments: dict[str, str],
    jira_projects: set[str],
    people: dict[str, uuid.UUID],
) -> ConvertContext:
    """The world the converter needs, bound to what exists RIGHT NOW."""
    return ConvertContext(
        attachment_url=lambda name: attachments.get(name, ""),
        page_url=lambda pid: f"/pages/{by_external[pid]}" if pid in by_external else "",
        page_url_by_title=lambda title, space: (
            f"/pages/{by_title[title]}" if title in by_title else ""
        ),
        user_ref=lambda username: (
            username, str(people[username]) if username in people else ""
        ),
        item_exists=lambda key: key.rsplit("-", 1)[0] in jira_projects,
        jira_base_url="",
        confluence_base_url=snapshot.base_url,
    )


def _nearest_imported(
    row: ConfluenceSnapshotPage, by_external: dict[str, uuid.UUID]
) -> uuid.UUID | None:
    """A hand-picked selection has holes in its lineage. Attaching to the nearest
    ancestor that DID import keeps the shape; the download already recorded a
    problem naming the gap, so this is not a silent flatten."""
    return by_external.get(row.parent_id) if row.parent_id else None


def _author_of(row: ConfluenceSnapshotPage) -> str:
    by = ((row.payload or {}).get("history") or {}).get("createdBy") or {}
    return by.get("username", "") or by.get("displayName", "")


async def _people(session: AsyncSession, mappings) -> dict[str, uuid.UUID]:
    """Confluence username → Radd user. Explicit mapping wins; otherwise matched
    by email and then by name, which is what makes a placeholder adoptable by a
    later AD import (spec 88)."""
    out: dict[str, uuid.UUID] = {}
    for entry in mappings.users:
        if entry.user_id:
            out[entry.username] = entry.user_id
            continue
        from sqlalchemy import func

        user = await session.scalar(
            select(User).where(func.lower(User.email) == (entry.email or entry.username).lower())
        ) or await session.scalar(
            select(User).where(func.lower(User.name) == entry.username.lower())
        )
        if user is not None:
            out[entry.username] = user.id
    return out


async def _any_admin(session: AsyncSession) -> uuid.UUID:
    from radd.modules.auth.types import InstanceRole

    user = await session.scalar(
        select(User).where(User.instance_role == InstanceRole.ADMIN.value).limit(1)
    )
    return user.id if user else uuid.uuid4()


async def _spaces(
    session: AsyncSession, run: ConfluenceRun, snapshot: ConfluenceSnapshot,
    mappings, actor_id: uuid.UUID, run_id: uuid.UUID | None, commit: bool,
) -> dict[str, uuid.UUID]:
    out: dict[str, uuid.UUID] = {}
    for entry in mappings.spaces:
        if entry.action is SpaceAction.IGNORE:
            continue
        if entry.action is SpaceAction.MAP and entry.space_id:
            out[entry.key] = entry.space_id
            continue
        existing = await page_spaces.find_space_by_external(
            session, snapshot.external_source, entry.key
        )
        if existing is not None:
            out[entry.key] = existing.id
            _bump(run, "spaces_reused")
            continue
        if not commit:
            # A dry run must still RESOLVE the space, or every page under it
            # counts as skipped and the preview reports "0 pages" for a run that
            # would import thousands. The id is a stand-in; nothing writes with it.
            out[entry.key] = uuid.uuid4()
            _bump(run, "spaces_created")
            continue
        space = await page_spaces.create_space(
            session,
            PageSpaceCreate(
                name=entry.target_name or entry.name or entry.key,
                external_source=snapshot.external_source,
                external_id=entry.key,
            ),
            actor_id,
            permissions=IMPORT_PERMISSIONS,
        )
        await ledger.created(session, run_id, LedgerEntity.SPACE, space.id, subject=entry.key)
        out[entry.key] = space.id
        _bump(run, "spaces_created")
    await session.commit()
    return out


async def _attachments(
    session: AsyncSession, run: ConfluenceRun, snapshot: ConfluenceSnapshot,
    by_external: dict[str, uuid.UUID], actor_id: uuid.UUID,
    run_id: uuid.UUID | None, commit: bool,
) -> dict[str, dict[str, str]]:
    """Cached bytes → real page attachments. Entity key `page`, NOT `doc_page`:
    that was renamed in RADD-701 and the old value 422s every upload."""
    out: dict[str, dict[str, str]] = {}
    for foreign_id, page_id in by_external.items():
        rows = await store.attachments(session, snapshot.id, foreign_id)
        urls: dict[str, str] = {}
        for row in rows:
            if not commit:
                _bump(run, "attachments")
                continue
            try:
                data = await attachments_service.read_blob(
                    session, row.storage_name, host_id=row.storage_host_id
                )
            except Exception as exc:  # noqa: BLE001
                _problem(run, Problem(
                    kind=ProblemKind.ATTACHMENT,
                    message=f"cached bytes for {row.filename!r} could not be read",
                    subject=row.filename, detail=str(exc),
                ))
                continue
            upload = UploadFile(file=io.BytesIO(data), filename=row.filename)
            attachment = await attachments_service.save_upload(
                session,
                entity_type="page",
                entity_id=page_id,
                upload=upload,
                actor_id=actor_id,
            )
            await ledger.created(
                session, run_id, LedgerEntity.ATTACHMENT, attachment.id, subject=row.filename
            )
            urls[row.filename] = f"/api/v1/attachments/{attachment.id}/download"
            _bump(run, "attachments")
        out[foreign_id] = urls
        await session.commit()
    return out


async def _reconvert(
    session: AsyncSession, run: ConfluenceRun, snapshot: ConfluenceSnapshot,
    rows: list[ConfluenceSnapshotPage], by_external, by_title,
    attachments_by_page, jira_projects, people, actor_id, run_id, commit: bool,
) -> None:
    if not commit:
        return
    from radd.modules.pages import service as pages_service
    from radd.modules.pages.schemas import PageUpdate

    for row in rows:
        page_id = by_external.get(row.page_id)
        if page_id is None:
            continue
        context = _context(
            snapshot, by_external, by_title,
            attachments_by_page.get(row.page_id, {}), jira_projects, people,
        )
        from .storage import convert

        markdown = convert(row.body, context).markdown
        await pages_service.update_page(
            session, page_id,
            # A construction pass, not an edit: it must not consume a version
            # number the page's real imported history needs.
            PageUpdate(body=markdown, suppress_version=True),
            actor_id,
            permissions=IMPORT_PERMISSIONS,
        )
    await session.commit()


async def _comments(
    session: AsyncSession, run: ConfluenceRun, snapshot: ConfluenceSnapshot,
    rows: list[ConfluenceSnapshotPage], by_external: dict[str, uuid.UUID],
    people: dict[str, uuid.UUID], actor_id: uuid.UUID, commit: bool,
) -> None:
    from radd.modules.auth.types import Permission

    for row in rows:
        page_id = by_external.get(row.page_id)
        if page_id is None:
            continue
        for comment in await store.comments(session, snapshot.id, row.page_id):
            if not commit:
                _bump(run, "comments")
                continue
            from .storage import ConvertContext as _Ctx, convert

            body = convert(comment.body, _Ctx(confluence_base_url=snapshot.base_url)).markdown
            actor = await session.get(User, people.get(comment.author, actor_id)) \
                or await session.get(User, actor_id)
            if actor is None:
                continue
            await comments_service.create_authorized_comment(
                session,
                page_id,
                CommentCreate(
                    body=body,
                    author_id=people.get(comment.author),
                    created_at=_parsed(comment.created_at),
                    anchor=None,
                ),
                actor,
                entity_type="page",
                # The import-friendly door: author and timestamp are honored only
                # for a caller holding PROJECT_MANAGE, which is what this says.
                permissions=frozenset({Permission.PROJECT_MANAGE}),
            )
            _bump(run, "comments")
        await session.commit()


async def _history(
    session: AsyncSession, run: ConfluenceRun, rows: list[ConfluenceSnapshotPage],
    by_external: dict[str, uuid.UUID], people: dict[str, uuid.UUID],
    actor_id: uuid.UUID, run_id: uuid.UUID | None, commit: bool,
) -> None:
    for row in rows:
        page_id = by_external.get(row.page_id)
        if page_id is None or not row.versions:
            continue
        written = await apply_page.write_history(
            session, page_id, list(row.versions),
            resolve_author=lambda name: people.get(name),
            actor_id=actor_id, run_id=run_id, commit=commit,
            context=ConvertContext(),
        )
        _bump(run, "versions", written)
        await session.commit()


def _parsed(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# --- failure + lifecycle ------------------------------------------------------


async def _fail(session: AsyncSession, run_id: uuid.UUID, detail: str) -> None:
    await session.rollback()
    run = await session.get(ConfluenceRun, run_id)
    if run is None:
        return
    _problem(run, Problem(kind=ProblemKind.FAILED, message=detail))
    run.stage = RunStage.FAILED.value
    run.finished_at = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()


async def start_run(
    session: AsyncSession, plan_id: uuid.UUID, *, dry_run: bool, actor_id: uuid.UUID
) -> ConfluenceRun:
    from radd.exceptions import ConflictError

    plan = await plan_service.get_plan(session, plan_id)
    problems = await plan_service.validate_plan(session, plan_id)
    if problems and not dry_run:
        raise ConflictError(
            ConfluenceEntity.RUN,
            reason=f"{len(problems)} plan problem(s) must be fixed first",
        )
    snapshot = await snapshot_service.require_complete(session, plan.snapshot_id)
    run = ConfluenceRun(
        plan_id=plan.id,
        snapshot_id=plan.snapshot_id,
        actor_id=actor_id,
        kind=RunKind.IMPORT.value,
        dry_run=dry_run,
        # Frozen, so a report read months later describes the decisions the run
        # actually made rather than whatever the plan has been edited to since.
        plan_snapshot={"mappings": plan.mappings, "options": plan.options},
        external_source=snapshot.external_source,
        stage=RunStage.PENDING.value,
        counts={}, problems=[], report={},
    )
    session.add(run)
    await session.flush()
    return run


def start(run_id: uuid.UUID) -> None:
    asyncio.create_task(execute(run_id))


async def mark_interrupted() -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(ConfluenceRun)
            .where(
                ConfluenceRun.stage.not_in([s.value for s in TERMINAL_RUN_STAGES]),
                ConfluenceRun.finished_at.is_(None),
            )
            .values(stage=RunStage.FAILED.value)
        )
        await session.commit()


async def list_runs(session: AsyncSession, limit: int = 50) -> list[ConfluenceRun]:
    result = await session.execute(
        select(ConfluenceRun)
        .order_by(ConfluenceRun.started_at.desc().nullslast())
        .limit(limit)
    )
    return list(result.scalars())


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> ConfluenceRun:
    from radd.exceptions import NotFoundError

    run = await session.get(ConfluenceRun, run_id)
    if run is None:
        raise NotFoundError(ConfluenceEntity.RUN, run_id)
    return run


async def request_cancel(session: AsyncSession, run_id: uuid.UUID) -> ConfluenceRun:
    run = await get_run(session, run_id)
    if RunStage(run.stage) not in TERMINAL_RUN_STAGES:
        run.stage = RunStage.CANCELED.value
        await session.flush()
    return run
