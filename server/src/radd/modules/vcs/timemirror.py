"""Mirroring time logged on a merge/pull request into the linked issue (RADD-1258).

The provider-neutral seam every connector calls. A connector fetches the time
entries for one ref in the host's own shape and hands them here as
`SourceEntry` rows; this module decides

- **which issue** each entry lands on — the first key in the ref's texts, in
  the order the connector supplies them (source branch, title, description),
  unless the entry's own summary names a key, which wins for that entry;
- **who** logged it — the provider account matched to a Radd user by email,
  else by the per-connection identity map (`vcs_user_links`), else NOBODY: the
  entry is parked in `vcs_pending_worklogs` and surfaces in Settings as an
  unmatched author, because a worklog on the wrong person makes the timesheet
  lie (CLAUDE.md: never invented data);
- **what category** — the repository's default, else the instance's
  `Development`, else none.

Then `timelogging.external.reconcile_external_worklogs` makes the rows match,
which is where "never twice" and "removal follows the source" live.
"""

import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.clock import utcnow
from radd.modules.auth import service as auth_service
from radd.modules.events import service as events
from radd.modules.items import service as items_service
from radd.modules.timelogging import categories as timelog_categories
from radd.modules.timelogging import external as timelog_external
from radd.modules.timelogging.types import DEFAULT_WORK_CATEGORIES

from .models import VcsPendingWorklog, VcsUserLink
from .types import VcsEntity, VcsMatchedBy, VcsProvider, VcsUserLinkEvent

logger = logging.getLogger(__name__)

# The same key grammar every connector's parsing.py uses: TD-123, word-bounded.
KEY_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]{0,9}-\d+)\b")


@dataclass(frozen=True)
class SourceEntry:
    """One time entry as the host reports it, before any resolution."""

    external_id: str
    seconds: int
    spent_on: date
    author_username: str
    author_email: str = ""
    note: str = ""


@dataclass
class MirrorReport:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    skipped_disabled: int = 0
    #: Entries parked because their author has no Radd account.
    pending: int = 0
    #: Entries dropped because neither the ref nor the entry names a known item.
    no_item: int = 0
    unmatched_authors: set[str] = field(default_factory=set)

    def absorb(self, other: timelog_external.ReconcileReport) -> None:
        self.created += other.created
        self.updated += other.updated
        self.deleted += other.deleted
        self.unchanged += other.unchanged
        self.skipped_disabled += other.skipped_disabled

    def as_dict(self) -> dict:
        return {
            "created": self.created,
            "updated": self.updated,
            "deleted": self.deleted,
            "unchanged": self.unchanged,
            "skipped_disabled": self.skipped_disabled,
            "pending": self.pending,
            "no_item": self.no_item,
            "unmatched_authors": sorted(self.unmatched_authors),
        }


def extract_keys(*texts: str | None) -> list[str]:
    seen: list[str] = []
    for text in texts:
        for match in KEY_RE.finditer(text or ""):
            key = match.group(1).upper()
            if key not in seen:
                seen.append(key)
    return seen


async def target_item_id(session: AsyncSession, *texts: str | None) -> uuid.UUID | None:
    """The FIRST key across `texts` (in order) that names a real item. One
    item, never a split: an MR mentioning three issues logs its time to the
    one its branch (then title, then description) is about."""
    for key in extract_keys(*texts):
        item = await items_service.find_item_by_key(session, key)
        if item is not None:
            return item.id
    return None


# --- authors ---


def _norm(username: str) -> str:
    return username.strip().lower()


async def resolve_author(
    session: AsyncSession,
    *,
    provider: VcsProvider,
    connection_id: uuid.UUID,
    username: str,
    email: str = "",
) -> uuid.UUID | None:
    """Provider account → Radd user id, or None.

    Order: an existing mapping for this connection; else a Radd account with
    the same email, which is then RECORDED as an email-matched mapping so the
    admin can see (and override) it; else None — never a guess.
    """
    username = _norm(username)
    if not username:
        return None
    link = await session.scalar(
        select(VcsUserLink).where(
            VcsUserLink.provider == provider.value,
            VcsUserLink.connection_id == connection_id,
            VcsUserLink.external_username == username,
        )
    )
    if link is not None:
        return link.user_id
    if email:
        user = await auth_service.get_user_by_email(session, email.strip().lower())
        if user is not None:
            await _record_link(
                session,
                provider=provider,
                connection_id=connection_id,
                username=username,
                user_id=user.id,
                matched_by=VcsMatchedBy.EMAIL,
                actor_id=None,
            )
            return user.id
    return None


async def _record_link(
    session: AsyncSession,
    *,
    provider: VcsProvider,
    connection_id: uuid.UUID,
    username: str,
    user_id: uuid.UUID,
    matched_by: VcsMatchedBy,
    actor_id: uuid.UUID | None,
) -> VcsUserLink:
    link = VcsUserLink(
        provider=provider.value,
        connection_id=connection_id,
        external_username=_norm(username),
        user_id=user_id,
        matched_by=matched_by.value,
    )
    session.add(link)
    await session.flush()
    await events.emit(
        session,
        event_type=VcsUserLinkEvent.CREATED,
        entity_type=VcsEntity.USER_LINK,
        entity_id=link.id,
        actor_id=actor_id,
        payload={
            "provider": provider.value,
            "connection_id": str(connection_id),
            "external_username": link.external_username,
            "user": await auth_service.user_ref_by_id(session, user_id),
            "matched_by": matched_by.value,
        },
    )
    return link


async def list_user_links(
    session: AsyncSession, *, provider: VcsProvider, connection_id: uuid.UUID
) -> list[VcsUserLink]:
    rows = await session.execute(
        select(VcsUserLink)
        .where(VcsUserLink.provider == provider.value, VcsUserLink.connection_id == connection_id)
        .order_by(VcsUserLink.external_username)
    )
    return list(rows.scalars())


async def set_user_link(
    session: AsyncSession,
    *,
    provider: VcsProvider,
    connection_id: uuid.UUID,
    username: str,
    user_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> VcsUserLink:
    """Map (or remap) a provider account by hand. Replaces an existing row so
    the admin's word beats an earlier email match."""
    await auth_service.get_user(session, user_id)  # 404s an unknown user
    existing = await session.scalar(
        select(VcsUserLink).where(
            VcsUserLink.provider == provider.value,
            VcsUserLink.connection_id == connection_id,
            VcsUserLink.external_username == _norm(username),
        )
    )
    if existing is not None:
        await _delete_link(session, existing, actor_id)
    return await _record_link(
        session,
        provider=provider,
        connection_id=connection_id,
        username=username,
        user_id=user_id,
        matched_by=VcsMatchedBy.MANUAL,
        actor_id=actor_id,
    )


async def _delete_link(session: AsyncSession, link: VcsUserLink, actor_id: uuid.UUID | None) -> None:
    await events.emit(
        session,
        event_type=VcsUserLinkEvent.DELETED,
        entity_type=VcsEntity.USER_LINK,
        entity_id=link.id,
        actor_id=actor_id,
        payload={
            "provider": link.provider,
            "connection_id": str(link.connection_id),
            "external_username": link.external_username,
            "user": await auth_service.user_ref_by_id(session, link.user_id),
        },
    )
    await session.delete(link)
    await session.flush()


async def delete_user_link(
    session: AsyncSession, link_id: uuid.UUID, *, actor_id: uuid.UUID | None
) -> None:
    link = await session.get(VcsUserLink, link_id)
    if link is not None:
        await _delete_link(session, link, actor_id)


async def forget_connection(
    session: AsyncSession, *, provider: VcsProvider, connection_id: uuid.UUID
) -> None:
    """A connector deleting a connection calls this: its mappings and parked
    entries go with it (no FK can, the connection tables are per connector)."""
    await session.execute(
        delete(VcsUserLink).where(
            VcsUserLink.provider == provider.value, VcsUserLink.connection_id == connection_id
        )
    )
    await session.execute(
        delete(VcsPendingWorklog).where(
            VcsPendingWorklog.provider == provider.value,
            VcsPendingWorklog.connection_id == connection_id,
        )
    )


# --- categories ---


async def default_category_id(
    session: AsyncSession, repo_category_id: uuid.UUID | None
) -> uuid.UUID | None:
    """The repository's chosen category, else the instance's first default
    (`Development`), else None — an item-anchored worklog may carry none."""
    if repo_category_id is not None:
        try:
            await timelog_categories.resolve_category(session, repo_category_id)
            return repo_category_id
        except Exception:  # archived or deleted since it was chosen
            logger.info("vcs timemirror: repo category %s is gone; using the default", repo_category_id)
    for category in await timelog_categories.list_categories(session):
        if category.name == DEFAULT_WORK_CATEGORIES[0]:
            return category.id
    return None


# --- the reconcile ---


async def reconcile(
    session: AsyncSession,
    *,
    provider: VcsProvider,
    connection_id: uuid.UUID,
    scope: str,
    ref_texts: Sequence[str | None],
    entries: Sequence[SourceEntry],
    category_id: uuid.UUID | None,
    note_prefix: str,
) -> MirrorReport:
    """Mirror the CURRENT time entries of one ref.

    `scope` is the ref's vcs external id (`pr:<repo>:<n>`), `ref_texts` the
    texts a key is looked for in (branch, title, description — in that order),
    `note_prefix` what a mirrored worklog's note starts with when the entry has
    no summary of its own ("Logged on !41 Fix the farm").
    """
    report = MirrorReport()
    default_item = await target_item_id(session, *ref_texts)
    resolved: list[timelog_external.ExternalEntry] = []
    pending_ids: set[str] = set()
    now = utcnow()

    for entry in entries:
        item_id = await target_item_id(session, entry.note) or default_item
        if item_id is None:
            report.no_item += 1
            continue
        note = entry.note.strip() or note_prefix
        author_id = await resolve_author(
            session,
            provider=provider,
            connection_id=connection_id,
            username=entry.author_username,
            email=entry.author_email,
        )
        if author_id is None:
            await _park(
                session,
                provider=provider,
                connection_id=connection_id,
                scope=scope,
                entry=entry,
                item_id=item_id,
                category_id=category_id,
                note=note,
                seen_at=now,
            )
            pending_ids.add(entry.external_id)
            report.pending += 1
            report.unmatched_authors.add(_norm(entry.author_username))
            continue
        resolved.append(
            timelog_external.ExternalEntry(
                external_id=entry.external_id,
                item_id=item_id,
                author_id=author_id,
                seconds=entry.seconds,
                worked_on=entry.spent_on,
                note=note,
                category_id=category_id,
            )
        )

    report.absorb(
        await timelog_external.reconcile_external_worklogs(
            session, source=provider.value, scope=scope, entries=resolved
        )
    )
    # Parked entries the source no longer has go too.
    stale = delete(VcsPendingWorklog).where(
        VcsPendingWorklog.provider == provider.value,
        VcsPendingWorklog.external_scope == scope,
    )
    if pending_ids:
        stale = stale.where(VcsPendingWorklog.external_id.not_in(pending_ids))
    await session.execute(stale)
    return report


async def _park(
    session: AsyncSession,
    *,
    provider: VcsProvider,
    connection_id: uuid.UUID,
    scope: str,
    entry: SourceEntry,
    item_id: uuid.UUID,
    category_id: uuid.UUID | None,
    note: str,
    seen_at,
) -> None:
    row = await session.scalar(
        select(VcsPendingWorklog).where(
            VcsPendingWorklog.provider == provider.value,
            VcsPendingWorklog.external_id == entry.external_id,
        )
    )
    if row is None:
        row = VcsPendingWorklog(
            provider=provider.value,
            connection_id=connection_id,
            external_scope=scope,
            external_id=entry.external_id,
        )
        session.add(row)
    row.external_username = _norm(entry.author_username)
    row.external_email = (entry.author_email or "").strip().lower()
    row.item_id = item_id
    row.category_id = category_id
    row.worked_on = entry.spent_on
    row.time_spent_seconds = entry.seconds
    row.note = note
    row.last_seen_at = seen_at
    await session.flush()


# --- unmatched authors + replay ---


@dataclass(frozen=True)
class UnmatchedAuthor:
    external_username: str
    external_email: str
    pending_entries: int
    pending_seconds: int
    last_seen_at: object


async def list_unmatched(
    session: AsyncSession, *, provider: VcsProvider, connection_id: uuid.UUID
) -> list[UnmatchedAuthor]:
    rows = await session.execute(
        select(
            VcsPendingWorklog.external_username,
            func.max(VcsPendingWorklog.external_email),
            func.count(),
            func.sum(VcsPendingWorklog.time_spent_seconds),
            func.max(VcsPendingWorklog.last_seen_at),
        )
        .where(
            VcsPendingWorklog.provider == provider.value,
            VcsPendingWorklog.connection_id == connection_id,
        )
        .group_by(VcsPendingWorklog.external_username)
        .order_by(VcsPendingWorklog.external_username)
    )
    return [
        UnmatchedAuthor(
            external_username=username,
            external_email=email or "",
            pending_entries=int(count),
            pending_seconds=int(seconds or 0),
            last_seen_at=seen,
        )
        for username, email, count, seconds, seen in rows.all()
    ]


async def map_and_replay(
    session: AsyncSession,
    *,
    provider: VcsProvider,
    connection_id: uuid.UUID,
    username: str,
    user_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> int:
    """Record the mapping, then turn every parked entry for that account into a
    real worklog — by external id, so a later reconcile from the source finds
    the same rows. Returns how many were replayed."""
    await set_user_link(
        session,
        provider=provider,
        connection_id=connection_id,
        username=username,
        user_id=user_id,
        actor_id=actor_id,
    )
    rows = await session.execute(
        select(VcsPendingWorklog).where(
            VcsPendingWorklog.provider == provider.value,
            VcsPendingWorklog.connection_id == connection_id,
            VcsPendingWorklog.external_username == _norm(username),
        )
    )
    replayed = 0
    for row in rows.scalars().all():
        entry = timelog_external.ExternalEntry(
            external_id=row.external_id,
            item_id=row.item_id,
            author_id=user_id,
            seconds=row.time_spent_seconds,
            worked_on=row.worked_on,
            note=row.note,
            category_id=row.category_id,
        )
        # Not a reconcile — that would delete the OTHER entries under the same
        # scope. A replay touches this one row only, so it goes through the
        # upsert; a project with time logging OFF receives nothing, the same
        # answer the reconcile gives, and the parked row is dropped either way.
        if await timelog_external.item_enabled(session, row.item_id):
            _worklog, outcome = await timelog_external.upsert_external_worklog(
                session, source=provider.value, scope=row.external_scope, entry=entry
            )
            replayed += 1 if outcome != "unchanged" else 0
        await session.delete(row)
    await session.flush()
    return replayed
