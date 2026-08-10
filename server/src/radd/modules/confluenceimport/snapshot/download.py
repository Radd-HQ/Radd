"""The snapshot download (spec 117).

Cache-first, as spec 100 established: a selection is fetched ONCE and every later
step reads these rows. Nothing after this touches the network, which is what makes
iterating on mappings free — fix a macro mapping and re-convert, no re-download.

The snapshot ROW is the progress bar. There is no job table and no event stream,
because a download is one in-process asyncio task with exactly one observer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import cast, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import SessionLocal

from .. import connections
from . import package
from ..client import ConfluenceClient, ConfluenceUnavailable
from ..models import (
    ConfluenceSnapshot,
    ConfluenceSnapshotAttachment,
    ConfluenceSnapshotComment,
    ConfluenceSnapshotPage,
)
from ..types import (
    ConfluenceCreds,
    ConfluencePage,
    Problem,
    ProblemKind,
    Scope,
    ScopeKind,
    SnapshotStage,
    TERMINAL_SNAPSHOT_STAGES,
)

logger = logging.getLogger(__name__)

#: Pages per transaction. Live progress without one enormous transaction.
COMMIT_EVERY = 25
#: A download reports at most this many problems; past it the count is the story.
MAX_RECORDED_PROBLEMS = 500


# --- progress bookkeeping -----------------------------------------------------


def _bump(snapshot: ConfluenceSnapshot, key: str, by: int = 1) -> None:
    counts = dict(snapshot.counts or {})
    counts[key] = counts.get(key, 0) + by
    snapshot.counts = counts


def _problem(snapshot: ConfluenceSnapshot, problem: Problem) -> None:
    problems = list(snapshot.problems or [])
    if len(problems) < MAX_RECORDED_PROBLEMS:
        problems.append(problem.as_dict())
        snapshot.problems = problems
    _bump(snapshot, "problems")


async def _canceled(session: AsyncSession, snapshot: ConfluenceSnapshot) -> bool:
    """Cooperative cancellation: the request lands on a DIFFERENT session, so the
    only way to see it is to re-read the column."""
    await session.refresh(snapshot, ["stage"])
    return SnapshotStage(snapshot.stage) is SnapshotStage.CANCELED


async def _stage(
    session: AsyncSession, snapshot: ConfluenceSnapshot, stage: SnapshotStage
) -> None:
    snapshot.stage = stage.value
    await session.commit()


# --- scope resolution ---------------------------------------------------------


def _resolve_scope(client: ConfluenceClient, scope: Scope) -> list[ConfluencePage]:
    """Turn any of the three selections into ONE list of pages.

    This is the whole reason `ScopeKind` exists: "the space", "this section", and
    "these pages" differ only here, and everything downstream sees one shape.
    """
    if scope.kind is ScopeKind.SPACE:
        return client.space_pages(scope.space_key)
    if scope.kind is ScopeKind.SUBTREE:
        root = client.page(scope.root_page_id)
        pages = [_page_from_payload(root)] + client.descendants(scope.root_page_id)
        if scope.max_depth is not None:
            pages = _capped(pages, scope.root_page_id, scope.max_depth)
        return pages
    # PAGES: exactly what was asked for, nothing implied.
    return [_page_from_payload(client.page(pid)) for pid in scope.page_ids]


def _page_from_payload(raw: dict) -> ConfluencePage:
    from ..client import _page_of

    return _page_of(raw, "")


def _capped(pages: list[ConfluencePage], root: str, max_depth: int) -> list[ConfluencePage]:
    """Keep pages within `max_depth` levels of the root."""
    parent_of = {p.id: p.parent_id for p in pages}
    kept: list[ConfluencePage] = []
    for page in pages:
        depth, cursor, guard = 0, page.parent_id, 0
        while cursor and cursor != root and guard < 100:
            depth += 1
            cursor = parent_of.get(cursor)
            guard += 1
        if depth < max_depth:
            kept.append(page)
    return kept


# --- the download -------------------------------------------------------------


async def execute(snapshot_id: uuid.UUID) -> None:
    """Run one download to a terminal stage. Never raises to the caller — the row
    carries the outcome, because there is nobody to catch it."""
    async with SessionLocal() as session:
        snapshot = await session.get(ConfluenceSnapshot, snapshot_id)
        if snapshot is None:
            return
        snapshot.started_at = datetime.now(UTC).replace(tzinfo=None)
        connection = (
            await connections.get_connection(session, snapshot.connection_id)
            if snapshot.connection_id
            else None
        )
        if connection is None:
            await _fail(session, snapshot_id, "the connection this snapshot used is gone")
            return
        creds = connections.creds_of(connection)
        try:
            await _pipeline(session, snapshot, creds)
        except ConfluenceUnavailable as exc:
            await _fail(session, snapshot_id, str(exc))
        except Exception as exc:  # noqa: BLE001 — the row is the only reporter
            logger.exception("confluence snapshot %s failed", snapshot_id)
            await _fail(session, snapshot_id, f"unexpected error: {exc}")


async def _pipeline(
    session: AsyncSession, snapshot: ConfluenceSnapshot, creds: ConfluenceCreds
) -> None:
    scope = Scope.from_dict(snapshot.scope)
    client = ConfluenceClient(creds)

    await _stage(session, snapshot, SnapshotStage.SPACES)
    spaces = await asyncio.to_thread(_catalog_spaces, client)
    snapshot.catalogs = {"spaces": spaces}
    await session.commit()

    await _stage(session, snapshot, SnapshotStage.TREE)
    pages = await asyncio.to_thread(_resolve_scope, client, scope)
    snapshot.page_count = len(pages)
    _bump(snapshot, "pages_found", len(pages))
    await session.commit()

    selected = {p.id for p in pages}
    await _stage(session, snapshot, SnapshotStage.BODIES)
    rows = await _bodies(session, snapshot, client, pages, selected)
    if await _canceled(session, snapshot):
        return

    if snapshot.include_history:
        await _stage(session, snapshot, SnapshotStage.VERSIONS)
        await _versions(session, snapshot, client, rows)

    if snapshot.include_comments:
        await _stage(session, snapshot, SnapshotStage.COMMENTS)
        await _comments(session, snapshot, client, rows)

    # People, resolved ONCE into the snapshot's catalog. Every later step reads it
    # offline, so the plan can show real names and the converter can emit real
    # mentions without going near the network.
    await _people_catalog(session, snapshot, client, rows)

    await _stage(session, snapshot, SnapshotStage.RESTRICTIONS)
    await _restrictions(session, snapshot, client, rows)

    if snapshot.include_attachments:
        await _stage(session, snapshot, SnapshotStage.ATTACHMENTS)
        await _attachments(session, snapshot, client, rows)

    # The package describes itself, so a directory copied to another machine —
    # or found on disk months later — says what it is without the database.
    await asyncio.to_thread(package.write_manifest, snapshot.id, {
        "snapshot_id": str(snapshot.id),
        "name": snapshot.name,
        "source": snapshot.external_source,
        "base_url": snapshot.base_url,
        "scope": snapshot.scope,
        "pages": snapshot.page_count,
        "counts": snapshot.counts,
        "downloaded_at": datetime.now(UTC).isoformat(),
    })
    snapshot.byte_size = await asyncio.to_thread(package.size_bytes, snapshot.id) or snapshot.byte_size

    snapshot.stage = SnapshotStage.DONE.value
    snapshot.finished_at = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()
    await asyncio.to_thread(client.close)


#: `<ri:user ri:userkey="…"/>` — Server/DC's mention form. The key is an opaque
#: 32-char hex handle, not a username, so it has to be resolved before anything
#: downstream can match a person.
_USERKEY_RE = re.compile(r'<ri:user\s+ri:userkey="([^"]+)"')
_USERNAME_RE = re.compile(r'<ri:user\s+ri:username="([^"]+)"')


async def _people_catalog(
    session: AsyncSession, snapshot: ConfluenceSnapshot,
    client: ConfluenceClient, rows: list[ConfluenceSnapshotPage],
) -> None:
    """Resolve every person the bodies mention, once, into the snapshot.

    Confluence mentions carry an internal user key rather than a username; left
    unresolved they surfaced as raw 32-character hex on the page and as
    "mention of unknown user 8a05808b6921…" in the report — unmatchable, and
    meaningless to read. One request per DISTINCT key, cached on the snapshot so
    planning and the run never repeat it.
    """
    keys: set[str] = set()
    for row in rows:
        keys.update(_USERKEY_RE.findall(row.body or ""))
    known = dict((snapshot.catalogs or {}).get("users") or {})
    people: dict[str, dict] = dict(known)

    for key in keys - known.keys():
        try:
            raw = await asyncio.to_thread(client.user_by_key, key)
        except ConfluenceUnavailable as exc:
            # A departed account 404s here. Recorded, not fatal: the mention
            # degrades to the key and the People table can still map it by hand.
            logger.info("could not resolve confluence user %s: %s", key, exc)
            continue
        people[key] = {
            "username": raw.get("username", "") or "",
            "display_name": raw.get("displayName", "") or "",
            "email": raw.get("email") or "",
        }
    # A username mention needs no lookup to MATCH, but it does to READ: a People
    # table listing `sfraeys` and `mcollie` asks someone to recognise
    # sAMAccountNames. Same catalog, so everything downstream has one place to ask.
    usernames: set[str] = set()
    for row in rows:
        usernames.update(_USERNAME_RE.findall(row.body or ""))
    # Comment AUTHORS are the other half, and the bigger one: bodies mention people
    # by user key, while a comment carries its author's username. Scanning only
    # bodies left the People table mixing resolved names with bare
    # sAMAccountNames, which reads as though half of them had failed.
    authors = await session.execute(
        select(ConfluenceSnapshotComment.author).where(
            ConfluenceSnapshotComment.snapshot_id == snapshot.id,
            ConfluenceSnapshotComment.author != "",
        )
    )
    usernames.update(name for (name,) in authors if name)
    for username in usernames - people.keys():
        try:
            raw = await asyncio.to_thread(client.user_by_username, username)
        except ConfluenceUnavailable:
            people[username] = {"username": username, "display_name": "", "email": ""}
            continue
        people[username] = {
            "username": raw.get("username", "") or username,
            "display_name": raw.get("displayName", "") or "",
            "email": raw.get("email") or "",
        }

    snapshot.catalogs = {**(snapshot.catalogs or {}), "users": people}
    _bump(snapshot, "people", len(people))
    await session.commit()


def _catalog_spaces(client: ConfluenceClient) -> list[dict]:
    return [
        {"key": s.key, "name": s.name, "id": s.id, "description": s.description}
        for s in client.spaces()
    ]


async def _bodies(
    session: AsyncSession,
    snapshot: ConfluenceSnapshot,
    client: ConfluenceClient,
    pages: list[ConfluencePage],
    selected: set[str],
) -> list[ConfluenceSnapshotPage]:
    rows: list[ConfluenceSnapshotPage] = []
    written: set[str] = set()
    for index, page in enumerate(pages):
        # The listing already de-duplicates, but a repeat here costs the ENTIRE
        # download to a primary-key violation rather than one page — cheap enough
        # to check twice for a failure that expensive.
        if page.id in written:
            continue
        written.add(page.id)
        if index % COMMIT_EVERY == 0:
            await session.commit()
            if await _canceled(session, snapshot):
                return rows
        try:
            payload = await asyncio.to_thread(client.page, page.id)
        except ConfluenceUnavailable as exc:
            _problem(snapshot, Problem(
                kind=ProblemKind.FAILED,
                message=f"could not download page {page.title!r}",
                subject=page.id, detail=str(exc),
            ))
            continue
        body = ((payload.get("body") or {}).get("storage") or {}).get("value", "")
        # A hand-picked selection has holes in its lineage. Recording the real
        # parent and letting the RUN reparent to the nearest imported ancestor is
        # honest; silently flattening to the space root would look like it worked.
        parent = page.parent_id
        if parent and parent not in selected:
            _problem(snapshot, Problem(
                kind=ProblemKind.PARENT,
                message=f"{page.title!r} has a parent outside this selection",
                subject=page.id,
                detail="it will be attached to the nearest imported ancestor",
            ))
        row = ConfluenceSnapshotPage(
            snapshot_id=snapshot.id,
            page_id=page.id,
            space_key=page.space_key,
            parent_id=parent,
            title=page.title,
            position=page.position,
            version=page.version,
            body=body,
            payload=payload,
            labels=list(page.labels),
        )
        session.add(row)
        rows.append(row)
        _bump(snapshot, "bodies")
        snapshot.byte_size = (snapshot.byte_size or 0) + len(body)
    await session.commit()
    return rows


async def _versions(
    session: AsyncSession, snapshot: ConfluenceSnapshot,
    client: ConfluenceClient, rows: list[ConfluenceSnapshotPage],
) -> None:
    """Historical revisions, only when asked for.

    Off by default because a live page in a real corpus sits at version 206, and
    pulling every revision of every page is one request per revision.
    """
    limit = snapshot.history_limit
    for index, row in enumerate(rows):
        if index % COMMIT_EVERY == 0:
            await session.commit()
            if await _canceled(session, snapshot):
                return
        # Revision N is the LIVE body; history is 1..N-1.
        wanted = list(range(1, row.version))
        if limit:
            wanted = wanted[-limit:]
        captured: list[dict] = []
        for number in wanted:
            try:
                payload = await asyncio.to_thread(client.version_body, row.page_id, number)
            except ConfluenceUnavailable:
                continue
            history = payload.get("history") or {}
            by = (payload.get("version") or {}).get("by") or history.get("createdBy") or {}
            captured.append({
                "version": number,
                "title": payload.get("title", row.title),
                "body": ((payload.get("body") or {}).get("storage") or {}).get("value", ""),
                "author": by.get("username", "") or by.get("displayName", ""),
                "author_email": by.get("email", "") or "",
                "when": (payload.get("version") or {}).get("when", ""),
            })
        row.versions = captured
        _bump(snapshot, "versions", len(captured))
    await session.commit()


async def _comments(
    session: AsyncSession, snapshot: ConfluenceSnapshot,
    client: ConfluenceClient, rows: list[ConfluenceSnapshotPage],
) -> None:
    for index, row in enumerate(rows):
        if index % COMMIT_EVERY == 0:
            await session.commit()
            if await _canceled(session, snapshot):
                return
        try:
            found = await asyncio.to_thread(client.comments, row.page_id)
        except ConfluenceUnavailable as exc:
            _problem(snapshot, Problem(
                kind=ProblemKind.FAILED,
                message=f"could not download comments for {row.title!r}",
                subject=row.page_id, detail=str(exc),
            ))
            continue
        for raw in found:
            history = raw.get("history") or {}
            by = history.get("createdBy") or {}
            inline = ((raw.get("extensions") or {}).get("inlineProperties") or {})
            session.add(ConfluenceSnapshotComment(
                snapshot_id=snapshot.id,
                comment_id=str(raw.get("id", "")),
                page_id=row.page_id,
                body=((raw.get("body") or {}).get("storage") or {}).get("value", ""),
                author=by.get("username", "") or by.get("displayName", ""),
                author_email=by.get("email", "") or "",
                created_at=history.get("createdDate", "") or "",
                # An inline comment's anchor is a text QUOTE, which is what
                # `comments.anchor` already stores — a character offset would not
                # survive the conversion to markdown.
                anchor={"quote": inline.get("originalSelection", "")} if inline else None,
            ))
            _bump(snapshot, "comments")
    await session.commit()


async def _restrictions(
    session: AsyncSession, snapshot: ConfluenceSnapshot,
    client: ConfluenceClient, rows: list[ConfluenceSnapshotPage],
) -> None:
    for index, row in enumerate(rows):
        if index % COMMIT_EVERY == 0:
            await session.commit()
            if await _canceled(session, snapshot):
                return
        try:
            row.restrictions = await asyncio.to_thread(client.restrictions, row.page_id)
        except ConfluenceUnavailable as exc:
            # "We could not read them" and "there were none" must not look the
            # same — one of those is a page that imports OPEN by mistake.
            _problem(snapshot, Problem(
                kind=ProblemKind.RESTRICTION,
                message=f"could not read restrictions for {row.title!r}",
                subject=row.page_id, detail=str(exc),
            ))
            continue
        # The envelope is always present; only a page that NAMES someone counts.
        from ..restrictions import is_restricted

        if is_restricted(row.restrictions):
            _bump(snapshot, "restricted_pages")
    await session.commit()


async def _attachments(
    session: AsyncSession, snapshot: ConfluenceSnapshot,
    client: ConfluenceClient, rows: list[ConfluenceSnapshotPage],
) -> None:
    """Manifest rows + bytes, straight onto disk in the snapshot's package."""
    for index, row in enumerate(rows):
        if index % COMMIT_EVERY == 0:
            await session.commit()
            if await _canceled(session, snapshot):
                return
        try:
            found = await asyncio.to_thread(client.attachments, row.page_id)
        except ConfluenceUnavailable as exc:
            _problem(snapshot, Problem(
                kind=ProblemKind.ATTACHMENT,
                message=f"could not list attachments for {row.title!r}",
                subject=row.page_id, detail=str(exc),
            ))
            continue
        for raw in found:
            download_path = ((raw.get("_links") or {}).get("download") or "")
            filename = raw.get("title", "")
            # Straight to disk. No spooling, no object store, and NO SIZE CAP:
            # a download is a cache, and refusing to cache a file we might import
            # is a decision for the import to make, not the download.
            attachment_id = str(raw.get("id", ""))
            path, handle = package.open_for_write(snapshot.id, attachment_id, filename)
            try:
                size = await asyncio.to_thread(
                    client.download_to, download_path, handle
                )
            except ConfluenceUnavailable as exc:
                handle.close()
                path.unlink(missing_ok=True)
                _problem(snapshot, Problem(
                    kind=ProblemKind.ATTACHMENT,
                    message=f"could not download {filename!r}",
                    subject=filename, detail=str(exc),
                ))
                continue
            finally:
                if not handle.closed:
                    handle.close()
            media = ((raw.get("extensions") or {}).get("mediaType") or "application/octet-stream")
            session.add(ConfluenceSnapshotAttachment(
                snapshot_id=snapshot.id,
                attachment_id=attachment_id,
                page_id=row.page_id,
                filename=filename,
                content_type=media,
                size_bytes=size,
                file_path=package.relative(path, snapshot.id),
                download_path=download_path,
            ))
            snapshot.byte_size = (snapshot.byte_size or 0) + size
            _bump(snapshot, "attachments")
    await session.commit()


# --- failure + lifecycle ------------------------------------------------------


async def _fail(session: AsyncSession, snapshot_id: uuid.UUID, detail: str) -> None:
    """Roll back FIRST: a poisoned session would make recording the failure raise
    too, and the row would sit forever claiming to be running."""
    await session.rollback()
    snapshot = await session.get(ConfluenceSnapshot, snapshot_id)
    if snapshot is None:
        return
    _problem(snapshot, Problem(kind=ProblemKind.FAILED, message=detail))
    snapshot.stage = SnapshotStage.FAILED.value
    snapshot.finished_at = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()


def start(snapshot_id: uuid.UUID) -> None:
    """Fire and forget. In-process, like every other job in this codebase."""
    asyncio.create_task(execute(snapshot_id))


async def mark_interrupted() -> None:
    """A restart abandons in-process tasks, so anything left mid-flight is failed
    on startup rather than sitting forever claiming to be running.

    It SAYS SO, too. Marking the row failed and leaving `problems` empty produces
    exactly the report this module spent a wave learning not to give: the word
    "failed" and no reason, indistinguishable from a real error — when the honest
    answer is "the server restarted underneath it, start it again".
    """
    note = json.dumps([Problem(
        kind=ProblemKind.FAILED,
        message="interrupted by a server restart — nothing was lost, "
                "start the download again",
    ).as_dict()])
    async with SessionLocal() as session:
        await session.execute(
            update(ConfluenceSnapshot)
            .where(
                ConfluenceSnapshot.stage.not_in([s.value for s in TERMINAL_SNAPSHOT_STAGES]),
                ConfluenceSnapshot.finished_at.is_(None),
            )
            .values(
                stage=SnapshotStage.FAILED.value,
                problems=ConfluenceSnapshot.problems.op("||")(cast(note, JSONB)),
            )
        )
        await session.commit()


async def list_snapshots(session: AsyncSession) -> list[ConfluenceSnapshot]:
    result = await session.execute(
        select(ConfluenceSnapshot).order_by(ConfluenceSnapshot.started_at.desc().nullslast())
    )
    return list(result.scalars())
