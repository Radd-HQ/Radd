"""Reading a cached snapshot (spec 100) — the offline source everything downstream
uses instead of Jira.

Deliberately streaming: an import walks tens of thousands of issues, and loading
them all into a list first is how a 45k-issue project turns into a memory
problem. `iter_issues` pages by primary key.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import JiraSnapshot, JiraSnapshotBlob, JiraSnapshotIssue
from ..types import SnapshotCatalog

# Rows per database page while walking a snapshot. Large enough to amortise the
# round-trip, small enough that one page of raw Jira JSON stays modest.
PAGE_ROWS = 200


def catalog(snapshot: JiraSnapshot, key: SnapshotCatalog) -> Any:
    """One captured Jira vocabulary, or an empty container of the right shape."""
    stored = (snapshot.catalogs or {}).get(key.value)
    if stored is not None:
        return stored
    return {} if key in (SnapshotCatalog.FIELDS, SnapshotCatalog.OPTION_SETS) else []


async def iter_issues(
    session: AsyncSession, snapshot_id: uuid.UUID
) -> AsyncIterator[JiraSnapshotIssue]:
    """Every cached issue, in key order, a page at a time."""
    after = ""
    while True:
        result = await session.execute(
            select(JiraSnapshotIssue)
            .where(
                JiraSnapshotIssue.snapshot_id == snapshot_id,
                JiraSnapshotIssue.jira_key > after,
            )
            .order_by(JiraSnapshotIssue.jira_key)
            .limit(PAGE_ROWS)
        )
        rows = list(result.scalars())
        if not rows:
            return
        for row in rows:
            yield row
        after = rows[-1].jira_key


async def get_issue(
    session: AsyncSession, snapshot_id: uuid.UUID, jira_key: str
) -> JiraSnapshotIssue | None:
    return await session.get(JiraSnapshotIssue, (snapshot_id, jira_key))


async def count_issues(session: AsyncSession, snapshot_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(JiraSnapshotIssue)
        .where(JiraSnapshotIssue.snapshot_id == snapshot_id)
    )
    return result.scalar() or 0


async def payload_bytes(session: AsyncSession, snapshot_id: uuid.UUID) -> int:
    """Roughly what the cached issues occupy — what the UI shows next to Delete.

    `pg_column_size` reports the COMPRESSED, TOASTed size, which is the honest
    number: raw Jira JSON compresses hard, and quoting the uncompressed length
    would overstate the cost of keeping a snapshot around by several times.
    """
    result = await session.execute(
        select(func.coalesce(func.sum(func.pg_column_size(JiraSnapshotIssue.payload)), 0)).where(
            JiraSnapshotIssue.snapshot_id == snapshot_id
        )
    )
    return int(result.scalar() or 0)


async def blobs(session: AsyncSession, snapshot_id: uuid.UUID) -> list[JiraSnapshotBlob]:
    result = await session.execute(
        select(JiraSnapshotBlob).where(JiraSnapshotBlob.snapshot_id == snapshot_id)
    )
    return list(result.scalars())


async def blobs_by_attachment(
    session: AsyncSession, snapshot_id: uuid.UUID
) -> dict[str, JiraSnapshotBlob]:
    """Jira attachment id → the stored blob, for the import's attachment stage."""
    return {b.jira_attachment_id: b for b in await blobs(session, snapshot_id)}


async def blob_count_for_host(session: AsyncSession, host_id: uuid.UUID) -> int:
    """How many snapshot blobs live on a storage host — the spec-102 delete guard."""
    result = await session.execute(
        select(func.count()).select_from(JiraSnapshotBlob).where(
            JiraSnapshotBlob.storage_host_id == host_id
        )
    )
    return int(result.scalar() or 0)
