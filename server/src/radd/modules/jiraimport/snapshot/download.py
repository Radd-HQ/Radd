"""The snapshot download: one JQL result set fetched once into `jira_snapshot_issues`.

Stages: CATALOGS → ISSUES → COMMENTS → WORKLOGS → HISTORY → ATTACHMENTS.
`/search` inlines only the first page of comments/worklogs/changelog and reports
the true `total`; any short list is backfilled from the issue's own endpoint.
The row is the progress bar; cancel is cooperative (stage re-read between pages).
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import UploadFile
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import SessionLocal
from radd.modules.attachments import service as attachments_service
from radd.modules.attachments.types import AttachmentTooLarge

from .. import connections
from ..client import JiraClient, JiraUnavailable
from ..issuemap import to_utc_naive
from ..models import JiraConnection, JiraSnapshot, JiraSnapshotBlob, JiraSnapshotIssue
from ..types import (
    TERMINAL_SNAPSHOT_STAGES,
    JiraCreds,
    Problem,
    ProblemKind,
    SnapshotCatalog,
    SnapshotStage,
)
from . import service, store
from radd.clock import utcnow

logger = logging.getLogger(__name__)

PAGE_RETRIES = 4  # a large download spans hundreds of pages — survive a blip
PAGE_RETRY_DELAY = 3.0
CHILD_PAGE = 100  # comments/worklogs/changelog page size
MAX_RECORDED_PROBLEMS = 500  # grouped in the UI

# Jira's instance-wide vocabularies, so the mapping step offers the real ones.
_VOCABULARIES: tuple[tuple[SnapshotCatalog, str], ...] = (
    (SnapshotCatalog.ISSUE_TYPES, "/issuetype"),
    (SnapshotCatalog.STATUSES, "/status"),
    (SnapshotCatalog.PRIORITIES, "/priority"),
    (SnapshotCatalog.LINK_TYPES, "/issueLinkType"),
)



def _jira_updated(fields: dict[str, Any]) -> datetime | None:
    """Jira's `fields.updated` as a naive-UTC datetime. `to_utc_naive` normalises
    Jira's `+HHMM` offset but hands back a string, and this column is a timestamp —
    a re-download compares it to decide what actually changed."""
    normalised = to_utc_naive(fields.get("updated"))
    if not normalised:
        return None
    try:
        return datetime.fromisoformat(normalised)
    except ValueError:
        return None


# --- progress bookkeeping -----------------------------------------------------


def _bump(snapshot: JiraSnapshot, key: str, by: int = 1) -> None:
    counts = dict(snapshot.counts or {})
    counts[key] = counts.get(key, 0) + by
    snapshot.counts = counts


def _problem(snapshot: JiraSnapshot, problem: Problem) -> None:
    _bump(snapshot, "problems")
    existing = list(snapshot.problems or [])
    if len(existing) < MAX_RECORDED_PROBLEMS:
        snapshot.problems = [*existing, problem.as_dict()]


async def _canceled(session: AsyncSession, snapshot: JiraSnapshot) -> bool:
    """Has someone asked this download to stop? Read from the database, not the
    in-memory object: the request arrives on a different session."""
    await session.refresh(snapshot, ["stage"])
    return SnapshotStage(snapshot.stage) is SnapshotStage.CANCELED


async def _advance(session: AsyncSession, snapshot: JiraSnapshot, stage: SnapshotStage) -> None:
    snapshot.stage = stage.value
    await session.commit()


# --- Jira calls (each runs in a worker thread) --------------------------------


def _fetch_catalogs(creds: JiraCreds, project_key: str) -> dict[str, Any]:
    """Every vocabulary in ONE client session. Best-effort per catalog: a Jira
    that has retired an endpoint must not sink the whole download."""
    catalogs: dict[str, Any] = {}
    failures: list[tuple[str, str]] = []
    with JiraClient(creds) as jira:
        catalogs[SnapshotCatalog.FIELDS.value] = jira.field_catalog()
        for key, path in _VOCABULARIES:
            try:
                catalogs[key.value] = jira.vocabulary(path)
            except JiraUnavailable as exc:
                catalogs[key.value] = []
                failures.append((path, str(exc)))
        if project_key:
            for key, fetch in (
                (SnapshotCatalog.VERSIONS, jira.project_versions),
                (SnapshotCatalog.COMPONENTS, jira.project_components),
            ):
                try:
                    catalogs[key.value] = fetch(project_key)
                except JiraUnavailable as exc:
                    catalogs[key.value] = []
                    failures.append((key.value, str(exc)))
    catalogs["_failures"] = failures
    return catalogs


def _search_page(creds: JiraCreds, jql: str, start_at: int, expand: list[str] | None) -> dict:
    with JiraClient(creds) as jira:
        return jira.search(jql, start_at=start_at, expand=expand)


def _fetch_children(creds: JiraCreds, jobs: list[tuple[str, str, int]]) -> dict[str, list]:
    """Backfill several issues' truncated child lists over ONE connection.

    `jobs` is (jira_key, kind, already_have). Batching them into a single thread
    call keeps the connection warm; doing one thread hop per issue would undo the
    keep-alive this whole module exists to get.
    """
    out: dict[str, list] = {}
    with JiraClient(creds) as jira:
        for key, kind, _have in jobs:
            collected: list = []
            start_at = 0
            while True:
                if kind == SnapshotStage.COMMENTS.value:
                    page = jira.issue_comments(key, start_at=start_at, max_results=CHILD_PAGE)
                    items = page.get("comments") or []
                elif kind == SnapshotStage.WORKLOGS.value:
                    page = jira.issue_worklogs(key, start_at=start_at, max_results=CHILD_PAGE)
                    items = page.get("worklogs") or []
                else:
                    page = jira.issue_changelog(key, start_at=start_at, max_results=CHILD_PAGE)
                    items = page.get("values") or page.get("histories") or []
                collected.extend(items)
                total = int(page.get("total", len(collected)))
                start_at += len(items)
                if not items or start_at >= total:
                    break
            out[f"{key}:{kind}"] = collected
    return out


def _fetch_blobs(creds: JiraCreds, wanted: list[dict[str, str]]) -> dict[str, bytes | str]:
    """Attachment bytes for a batch, over one connection. A failure yields the
    error string instead of bytes so the caller can record which file and why."""
    out: dict[str, bytes | str] = {}
    with JiraClient(creds) as jira:
        for item in wanted:
            try:
                out[item["id"]] = jira.fetch_binary(item["url"])
            except JiraUnavailable as exc:
                out[item["id"]] = str(exc)
    return out


# --- stages -------------------------------------------------------------------


async def _run_catalogs(
    session: AsyncSession, snapshot: JiraSnapshot, creds: JiraCreds
) -> None:
    await _advance(session, snapshot, SnapshotStage.CATALOGS)
    catalogs = await asyncio.to_thread(_fetch_catalogs, creds, snapshot.jira_project_key)
    for path, error in catalogs.pop("_failures", []):
        _problem(
            snapshot,
            Problem(
                kind=ProblemKind.CATALOG_FETCH,
                message="a Jira vocabulary could not be read — mapping falls back to what the issues show",
                subject=path,
                detail=error,
            ),
        )
    snapshot.catalogs = catalogs
    _bump(snapshot, "catalog_fields", len(catalogs.get(SnapshotCatalog.FIELDS.value) or {}))
    await session.commit()


async def _run_issues(session: AsyncSession, snapshot: JiraSnapshot, creds: JiraCreds) -> None:
    """Page the JQL and cache every issue. Committed per page, so a download that
    dies half way keeps what it already has."""
    await _advance(session, snapshot, SnapshotStage.ISSUES)
    # `ORDER BY created ASC` is appended when the caller left the ordering open:
    # Jira pages by offset, so an unstable sort silently skips and repeats rows as
    # the result set shifts under a long download.
    jql = _stable_jql(snapshot.jql)
    expand = ["changelog"] if snapshot.include_history else None
    start_at = 0
    while True:
        if await _canceled(session, snapshot):
            return
        page = await _page_with_retry(session, snapshot, creds, jql, start_at, expand)
        issues = page.get("issues") or []
        if not issues:
            break
        total = int(page.get("total", 0))
        if not snapshot.counts.get("issues_total"):
            _bump(snapshot, "issues_total", total)
        await _store_page(session, snapshot, issues)
        start_at += len(issues)
        _bump(snapshot, "issues", len(issues))
        await session.commit()
        if start_at >= total:
            break


def _stable_jql(jql: str) -> str:
    return jql if "order by" in jql.lower() else f"{jql} ORDER BY created ASC"


async def _page_with_retry(
    session: AsyncSession,
    snapshot: JiraSnapshot,
    creds: JiraCreds,
    jql: str,
    start_at: int,
    expand: list[str] | None,
) -> dict:
    for attempt in range(PAGE_RETRIES):
        try:
            return await asyncio.to_thread(_search_page, creds, jql, start_at, expand)
        except JiraUnavailable as exc:
            if attempt == PAGE_RETRIES - 1:
                raise
            _bump(snapshot, "page_retries")
            logger.warning("snapshot: page at %d failed (%s) — retrying", start_at, exc)
            await session.commit()
            await asyncio.sleep(PAGE_RETRY_DELAY)
    raise JiraUnavailable("exhausted page retries")  # unreachable


async def _store_page(
    session: AsyncSession, snapshot: JiraSnapshot, issues: list[dict]
) -> None:
    """Upsert a page. An upsert (not an insert) so re-downloading over an existing
    snapshot refreshes it rather than colliding."""
    rows = [
        {
            "snapshot_id": snapshot.id,
            "jira_key": issue["key"],
            "jira_id": str(issue.get("id", "")),
            "jira_updated_at": _jira_updated(issue.get("fields") or {}),
            "payload": issue,
        }
        for issue in issues
        if issue.get("key")
    ]
    if not rows:
        return
    await session.execute(
        pg_insert(JiraSnapshotIssue)
        .values(rows)
        .on_conflict_do_update(
            index_elements=[JiraSnapshotIssue.snapshot_id, JiraSnapshotIssue.jira_key],
            set_={
                "jira_id": pg_insert(JiraSnapshotIssue).excluded.jira_id,
                "jira_updated_at": pg_insert(JiraSnapshotIssue).excluded.jira_updated_at,
                "payload": pg_insert(JiraSnapshotIssue).excluded.payload,
            },
        )
    )


# The container Jira uses for each truncated child list, and where the items sit.
_CHILD_SHAPES: dict[str, tuple[str, str]] = {
    "comments": ("comment", "comments"),
    "worklogs": ("worklog", "worklogs"),
}


async def _run_child_backfill(
    session: AsyncSession, snapshot: JiraSnapshot, creds: JiraCreds, kind: str
) -> None:
    """Re-fetch every issue whose inline child list is shorter than its `total`."""
    stage = SnapshotStage.COMMENTS if kind == SnapshotStage.COMMENTS.value else SnapshotStage.WORKLOGS
    await _advance(session, snapshot, stage)
    container, item_key = _CHILD_SHAPES[kind]

    batch: list[tuple[str, str, int]] = []
    async for row in store.iter_issues(session, snapshot.id):
        blob = (row.payload.get("fields") or {}).get(container) or {}
        have = len(blob.get(item_key) or [])
        total = int(blob.get("total", have))
        if total > have:
            batch.append((row.jira_key, kind, have))
        if len(batch) >= 25:
            await _apply_child_batch(session, snapshot, creds, batch, container, item_key)
            batch = []
            if await _canceled(session, snapshot):
                return
    if batch:
        await _apply_child_batch(session, snapshot, creds, batch, container, item_key)


async def _apply_child_batch(
    session: AsyncSession,
    snapshot: JiraSnapshot,
    creds: JiraCreds,
    batch: list[tuple[str, str, int]],
    container: str,
    item_key: str,
) -> None:
    kind = batch[0][1]
    try:
        fetched = await asyncio.to_thread(_fetch_children, creds, batch)
    except JiraUnavailable as exc:
        for key, _kind, _have in batch:
            _problem(
                snapshot,
                Problem(
                    kind=ProblemKind.COMMENTS_FETCH
                    if kind == SnapshotStage.COMMENTS.value
                    else ProblemKind.WORKLOGS_FETCH,
                    message=f"could not read the full {kind} list — only the first page is cached",
                    subject=key,
                    detail=str(exc),
                ),
            )
        await session.commit()
        return

    for key, _kind, have in batch:
        items = fetched.get(f"{key}:{kind}") or []
        if not items:
            continue
        row = await store.get_issue(session, snapshot.id, key)
        if row is None:
            continue
        payload = dict(row.payload)
        fields = dict(payload.get("fields") or {})
        blob = dict(fields.get(container) or {})
        blob[item_key] = items
        blob["total"] = len(items)
        blob["maxResults"] = len(items)
        fields[container] = blob
        payload["fields"] = fields
        row.payload = payload
        _bump(snapshot, f"{kind}_backfilled", len(items) - have)
        _bump(snapshot, f"{kind}_backfilled_issues")
    await session.commit()


async def _run_history_backfill(
    session: AsyncSession, snapshot: JiraSnapshot, creds: JiraCreds
) -> None:
    """`expand=changelog` also truncates on a long-lived issue."""
    await _advance(session, snapshot, SnapshotStage.HISTORY)
    batch: list[tuple[str, str, int]] = []
    async for row in store.iter_issues(session, snapshot.id):
        changelog = row.payload.get("changelog") or {}
        have = len(changelog.get("histories") or [])
        if int(changelog.get("total", have)) > have:
            batch.append((row.jira_key, "history", have))
        if len(batch) >= 25:
            await _apply_history_batch(session, snapshot, creds, batch)
            batch = []
            if await _canceled(session, snapshot):
                return
    if batch:
        await _apply_history_batch(session, snapshot, creds, batch)


async def _apply_history_batch(
    session: AsyncSession,
    snapshot: JiraSnapshot,
    creds: JiraCreds,
    batch: list[tuple[str, str, int]],
) -> None:
    try:
        fetched = await asyncio.to_thread(_fetch_children, creds, batch)
    except JiraUnavailable as exc:
        for key, _kind, _have in batch:
            _problem(
                snapshot,
                Problem(
                    kind=ProblemKind.HISTORY_FETCH,
                    message="could not read the full change history — only the first page is cached",
                    subject=key,
                    detail=str(exc),
                ),
            )
        await session.commit()
        return
    for key, _kind, have in batch:
        items = fetched.get(f"{key}:history") or []
        if not items:
            continue
        row = await store.get_issue(session, snapshot.id, key)
        if row is None:
            continue
        payload = dict(row.payload)
        payload["changelog"] = {"histories": items, "total": len(items)}
        row.payload = payload
        _bump(snapshot, "history_backfilled", len(items) - have)
    await session.commit()


async def _run_attachments(
    session: AsyncSession, snapshot: JiraSnapshot, creds: JiraCreds
) -> None:
    """Attachment bytes → the attachment store; `jira_snapshot_blobs` indexes them."""
    await _advance(session, snapshot, SnapshotStage.ATTACHMENTS)
    have = set((await store.blobs_by_attachment(session, snapshot.id)).keys())
    batch: list[dict[str, str]] = []
    async for row in store.iter_issues(session, snapshot.id):
        for attachment in (row.payload.get("fields") or {}).get("attachment") or []:
            aid = str(attachment.get("id") or "")
            url = attachment.get("content") or ""
            if not aid or not url or aid in have:
                continue
            batch.append(
                {
                    "id": aid,
                    "url": url,
                    "key": row.jira_key,
                    "filename": str(attachment.get("filename") or aid)[:300],
                    "content_type": str(attachment.get("mimeType") or "")[:120],
                }
            )
        if len(batch) >= 10:
            await _apply_blob_batch(session, snapshot, creds, batch)
            batch = []
            if await _canceled(session, snapshot):
                return
    if batch:
        await _apply_blob_batch(session, snapshot, creds, batch)


async def _apply_blob_batch(
    session: AsyncSession, snapshot: JiraSnapshot, creds: JiraCreds, batch: list[dict[str, str]]
) -> None:
    fetched = await asyncio.to_thread(_fetch_blobs, creds, batch)
    for item in batch:
        data = fetched.get(item["id"])
        if not isinstance(data, bytes):
            _problem(
                snapshot,
                Problem(
                    kind=ProblemKind.ATTACHMENT_FETCH,
                    message="an attachment could not be downloaded",
                    subject=f"{item['key']} · {item['filename']}",
                    detail=str(data or "no content"),
                ),
            )
            continue
        upload = UploadFile(file=io.BytesIO(data), filename=item["filename"])
        try:
            ref = await attachments_service.save_blob(
                session, upload, content_type=item["content_type"]
            )
        except AttachmentTooLarge as exc:
            _problem(
                snapshot,
                Problem(
                    kind=ProblemKind.ATTACHMENT_TOO_LARGE,
                    message="an attachment is larger than this instance allows",
                    subject=f"{item['key']} · {item['filename']}",
                    detail=str(exc),
                ),
            )
            continue
        session.add(
            JiraSnapshotBlob(
                snapshot_id=snapshot.id,
                jira_attachment_id=item["id"],
                jira_key=item["key"],
                storage_name=ref.storage_name,
                storage_host_id=ref.host_id,
                filename=item["filename"],
                content_type=item["content_type"],
                size_bytes=ref.size_bytes,
            )
        )
        _bump(snapshot, "attachments")
        _bump(snapshot, "attachment_bytes", ref.size_bytes)
    await session.commit()


# --- the job ------------------------------------------------------------------


async def execute(snapshot_id: uuid.UUID) -> None:
    """Run one download to completion in its own session. Never raises — a fatal
    problem is recorded on the snapshot and the stage set to FAILED."""
    async with SessionLocal() as session:
        snapshot = await session.get(JiraSnapshot, snapshot_id)
        if snapshot is None:
            return
        connection = (
            await session.get(JiraConnection, snapshot.connection_id)
            if snapshot.connection_id
            else None
        )
        if connection is None:
            await _fail(
                session, snapshot_id, "the Jira connection for this download no longer exists"
            )
            return
        creds = connections.creds_of(connection)
        snapshot.started_at = utcnow()
        await session.commit()

        try:
            await _run_catalogs(session, snapshot, creds)
            await _run_issues(session, snapshot, creds)
            if not await _canceled(session, snapshot):
                await _run_child_backfill(session, snapshot, creds, "comments")
            if not await _canceled(session, snapshot):
                await _run_child_backfill(session, snapshot, creds, "worklogs")
            if snapshot.include_history and not await _canceled(session, snapshot):
                await _run_history_backfill(session, snapshot, creds)
            if snapshot.include_attachments and not await _canceled(session, snapshot):
                await _run_attachments(session, snapshot, creds)
        except JiraUnavailable as exc:
            await _fail(session, snapshot_id, f"Jira became unreachable: {exc}")
            return
        except Exception as exc:  # noqa: BLE001 — the job must never crash the process
            logger.exception("snapshot %s failed", snapshot_id)
            await _fail(session, snapshot_id, f"unexpected error: {exc}")
            return

        # A cancel still keeps what was downloaded, and is still sized.
        canceled = await _canceled(session, snapshot)
        await service.refresh_size(session, snapshot)
        snapshot.stage = (SnapshotStage.CANCELED if canceled else SnapshotStage.DONE).value
        snapshot.finished_at = utcnow()
        await session.commit()


async def _fail(session: AsyncSession, snapshot_id: uuid.UUID, message: str) -> None:
    """Record why the download stopped. Takes an id and rolls back FIRST: the failed
    page may have poisoned the session, and `rollback()` expires every loaded instance."""
    await session.rollback()
    fresh = await session.get(JiraSnapshot, snapshot_id)
    if fresh is None:
        return
    _problem(fresh, Problem(kind=ProblemKind.JIRA_UNREACHABLE, message=message))
    fresh.stage = SnapshotStage.FAILED.value
    fresh.finished_at = utcnow()
    await session.commit()


def start(snapshot_id: uuid.UUID) -> None:
    """Fire the download as an in-process task; the snapshot row tracks it."""
    from radd.kernel.runtime import spawn
    spawn(execute(snapshot_id))  # noqa: RUF006 — tracked by the row


async def mark_interrupted() -> None:
    """Startup hook: a download running when the process died is not coming back."""
    async with SessionLocal() as session:
        await session.execute(
            update(JiraSnapshot)
            .where(
                JiraSnapshot.finished_at.is_(None),
                JiraSnapshot.stage.not_in([s.value for s in TERMINAL_SNAPSHOT_STAGES]),
            )
            .values(stage=SnapshotStage.FAILED.value, finished_at=utcnow())
        )
        await session.commit()
