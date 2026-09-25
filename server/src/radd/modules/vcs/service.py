import uuid
from datetime import datetime, timezone
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.kernel import changes
from radd.modules.events import service as events
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from .models import ItemVcsLink
from .schemas import VcsLinkCreate
from .types import VcsEntity, VcsEvent, VcsProvider, VcsRefType
from radd.clock import utcnow


async def link_vcs(
    session: AsyncSession,
    item_id: uuid.UUID,
    data: VcsLinkCreate,
    actor_id: uuid.UUID | None = None,
    connection_id: uuid.UUID | None = None,
) -> ItemVcsLink:
    return await _insert_link(
        session,
        item_id,
        ref_type=data.ref_type,
        provider=data.provider,
        external_id=data.external_id,
        title=data.title,
        url=data.url,
        status=data.status,
        actor_id=actor_id,
    )


async def unlink_vcs(
    session: AsyncSession, link_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    link = await get_vcs_link(session, link_id)
    await session.delete(link)
    await session.flush()
    await _emit(session, VcsEvent.UNLINKED, link, actor_id)


async def get_vcs_link(session: AsyncSession, link_id: uuid.UUID) -> ItemVcsLink:
    link = await session.get(ItemVcsLink, link_id)
    if link is None:
        raise NotFoundError(VcsEntity.VCS_LINK, link_id)
    return link


async def list_for_item(session: AsyncSession, item_id: uuid.UUID) -> list[ItemVcsLink]:
    result = await session.execute(
        select(ItemVcsLink).where(ItemVcsLink.item_id == item_id).order_by(ItemVcsLink.created_at)
    )
    return list(result.scalars())


async def upsert_vcs_link(
    session: AsyncSession,
    item_id: uuid.UUID,
    *,
    provider: VcsProvider,
    ref_type: VcsRefType,
    external_id: str,
    title: str,
    url: str,
    status: str = "",
    actor_id: uuid.UUID | None = None,
    connection_id: uuid.UUID | None = None,
) -> ItemVcsLink:
    """The CONNECTOR SEAM: the write-path GitLab/GitHub/Forgejo connectors call to keep an
    item's dev panel in sync. When `external_id` is set, find the existing row matched by
    (item_id, provider, connection_id, external_id) and update it in place (title/url/status/ref_type);
    otherwise create a fresh link. Emits vcs.updated on update, vcs.linked on create.

    The reference identity is UNIQUE by index (RADD-1124), and that index — not the lookup —
    is what guarantees one row: two deliveries of the same push racing each other
    both miss the lookup, one insert wins, and the loser's conflict is caught here
    and turned into the update it should have been.
    """
    existing = await _find_link(session, item_id, provider, external_id, connection_id) if external_id else None
    if existing is None:
        try:
            return await _insert_link(
                session,
                item_id,
                ref_type=ref_type,
                provider=provider,
                external_id=external_id,
                title=title,
                url=url,
                status=status,
                actor_id=actor_id, connection_id=connection_id,
            )
        except IntegrityError:
            existing = await _find_link(session, item_id, provider, external_id, connection_id)
            if existing is None:
                raise
    before = changes.snapshot(existing, ("ref_type", "title", "url", "status"))
    existing.ref_type = ref_type.value
    existing.title = title
    existing.url = url
    existing.status = status
    await session.flush()
    await _emit(session, VcsEvent.UPDATED, existing, actor_id, changes.diff_object(existing, before))
    return existing


async def _find_link(
    session: AsyncSession, item_id: uuid.UUID, provider: VcsProvider, external_id: str, connection_id: uuid.UUID | None = None
) -> ItemVcsLink | None:
    return await session.scalar(
        select(ItemVcsLink).where(
            ItemVcsLink.item_id == item_id,
            ItemVcsLink.provider == provider.value,
            ItemVcsLink.external_id == external_id,
            ItemVcsLink.connection_id == connection_id,
        )
    )


async def _insert_link(
    session: AsyncSession,
    item_id: uuid.UUID,
    *,
    ref_type: VcsRefType,
    provider: VcsProvider,
    external_id: str,
    title: str,
    url: str,
    status: str,
    actor_id: uuid.UUID | None,
    connection_id: uuid.UUID | None = None,
) -> ItemVcsLink:
    """Insert under a SAVEPOINT so a unique-index refusal leaves the caller's
    transaction usable — the upsert then updates the row that won."""
    link = ItemVcsLink(
        item_id=item_id,
        ref_type=ref_type.value,
        provider=provider.value,
        title=title,
        url=url,
        status=status,
        external_id=external_id,
        created_by=actor_id,
        connection_id=connection_id,
    )
    async with session.begin_nested():
        session.add(link)
        await session.flush()
    await _emit(session, VcsEvent.LINKED, link, actor_id)
    return link


async def _emit(
    session: AsyncSession,
    event_type: VcsEvent,
    link: ItemVcsLink,
    actor_id: uuid.UUID | None,
    diff: list[dict] | None = None,
) -> None:
    item = await items_service.require_item(session, link.item_id)
    await projects_service.get_project(session, item.project_id)
    await events.emit(
        session,
        event_type=event_type,
        entity_type=VcsEntity.VCS_LINK,
        entity_id=link.id,
        actor_id=actor_id,
        subjects={"item": link.item_id},
        payload={
            "ref_type": link.ref_type,
            "provider": link.provider,
            "title": link.title,
            "url": link.url,
            "status": link.status,
        },
        changes=diff,
    )


async def links_for_refs(
    session: AsyncSession, *, provider: str, external_ids: Sequence[str], connection_id: uuid.UUID | None = None, repo=None
) -> list[ItemVcsLink]:
    """Every link naming one of these refs (RADD-1255) — what a pipeline or a
    deployment for a ref is about. A ref no issue mentions has none, and so
    causes nothing: linking is the key mention's job."""
    if not external_ids:
        return []
    query = select(ItemVcsLink).where(
        ItemVcsLink.provider == provider, ItemVcsLink.external_id.in_(list(external_ids)),
        ItemVcsLink.connection_id == connection_id)
    rows = await session.execute(_repo_scope(query, repo))
    return list(rows.scalars())


def _repo_scope(query, repo):
    if repo is not None and not repo.link_all_projects:
        from radd.modules.items.models import WorkItem
        query = query.join(WorkItem, WorkItem.id == ItemVcsLink.item_id).where(WorkItem.project_id == repo.project_id)
    return query


def _source_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


async def set_ci_state(
    session: AsyncSession, *, provider: str, external_ids: Sequence[str],
    ci_state: str, ci_url: str = "", run_id: int | None = None,
    source_updated_at: str = "", connection_id: uuid.UUID | None = None,
    report_key: str = "pipeline", head_sha: str = "", source_started_at: str = "",
    attempt: int = 1, repo=None,
) -> list[ItemVcsLink]:
    """Order each CI stream independently and summarize all reported checks.

    A workflow result is not a statement about every required check. Repeated
    notifications and reports from superseded runs do not emit another event.
    """
    query = select(ItemVcsLink).where(
        ItemVcsLink.provider == provider, ItemVcsLink.connection_id == connection_id,
        ItemVcsLink.external_id.in_(external_ids)
    )
    links = list((await session.scalars(_repo_scope(query, repo).order_by(ItemVcsLink.id)
        .with_for_update(of=ItemVcsLink).execution_options(populate_existing=True))).all())
    reported_at = _source_time(source_updated_at)
    started_at = _source_time(source_started_at)
    terminal = {"success", "failure", "cancelled"}
    changed = []
    for link in links:
        reports = dict(link.ci_reports or {})
        previous = reports.get(report_key, {})
        if not reports and report_key == "pipeline" and link.ci_run_id is not None:
            previous = {"run_id": link.ci_run_id, "state": link.ci_state, "url": link.ci_url,
                "updated_at": link.ci_source_updated_at.isoformat() if link.ci_source_updated_at else ""}
        if previous:
            old_id = previous.get("run_id")
            if run_id is not None and old_id is not None:
                if (run_id, attempt) < (old_id, previous.get("attempt", 1)):
                    continue
            same_run = run_id == old_id and attempt == previous.get("attempt", 1)
            old_time = _source_time(previous.get("updated_at", ""))
            if same_run:
                if reported_at and old_time and reported_at < old_time:
                    continue
                if previous.get("state") in terminal and ci_state not in terminal:
                    continue
                if previous.get("state") == ci_state and previous.get("url") == ci_url and previous.get("sha", "") == head_sha:
                    continue
        if head_sha and link.ci_head_sha and head_sha != link.ci_head_sha:
            # An older commit's delayed result must not repaint the branch.
            if not started_at or (link.ci_head_started_at and started_at <= link.ci_head_started_at):
                continue
            reports = {}
        if head_sha:
            link.ci_head_sha = head_sha
            if started_at and (not link.ci_head_started_at or started_at > link.ci_head_started_at):
                link.ci_head_started_at = started_at
        reports[report_key] = {"state": ci_state, "url": ci_url, "run_id": run_id,
            "attempt": attempt, "sha": head_sha,
            "updated_at": reported_at.isoformat() if reported_at else ""}
        link.ci_reports = reports
        states = {report["state"] for report in reports.values()}
        link.ci_state = next((state for state in ("failure", "running", "cancelled", "unknown", "success") if state in states), "unknown")
        link.ci_url = ci_url
        link.ci_run_id = run_id
        link.ci_source_updated_at = reported_at
        link.ci_updated_at = utcnow()
        if (previous.get("state"), previous.get("run_id"), previous.get("attempt", 1), previous.get("sha", "")) != (ci_state, run_id, attempt, head_sha):
            changed.append(link)
    await session.flush()
    return changed
