"""Offline reads over a downloaded snapshot (spec 117).

Everything after the download reads through here, so the rest of the importer has
no idea the network exists.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    ConfluenceSnapshotAttachment,
    ConfluenceSnapshotComment,
    ConfluenceSnapshotPage,
)


async def pages(
    session: AsyncSession, snapshot_id: uuid.UUID
) -> list[ConfluenceSnapshotPage]:
    """Every cached page, PARENTS FIRST.

    Ordering matters to the run: a page cannot be created before its parent
    exists, and sorting by depth here means the writer never has to defer. Depth
    is computed in Python because it is a tree walk, not a query.
    """
    result = await session.execute(
        select(ConfluenceSnapshotPage)
        .where(ConfluenceSnapshotPage.snapshot_id == snapshot_id)
        .order_by(ConfluenceSnapshotPage.position, ConfluenceSnapshotPage.title)
    )
    rows = list(result.scalars())
    return _parents_first(rows)


def _parents_first(rows: list[ConfluenceSnapshotPage]) -> list[ConfluenceSnapshotPage]:
    by_id = {row.page_id: row for row in rows}
    depth: dict[str, int] = {}

    def depth_of(page_id: str, guard: int = 0) -> int:
        if page_id in depth:
            return depth[page_id]
        row = by_id.get(page_id)
        parent = row.parent_id if row else None
        # A loop already in the data must read as a finite depth rather than hang
        # the import — the same rule the page-tree walks follow.
        if row is None or not parent or parent not in by_id or guard > 100:
            depth[page_id] = 0
        else:
            depth[page_id] = depth_of(parent, guard + 1) + 1
        return depth[page_id]

    return sorted(rows, key=lambda r: (depth_of(r.page_id), r.position, r.title))


async def comments(
    session: AsyncSession, snapshot_id: uuid.UUID, page_id: str
) -> list[ConfluenceSnapshotComment]:
    result = await session.execute(
        select(ConfluenceSnapshotComment).where(
            ConfluenceSnapshotComment.snapshot_id == snapshot_id,
            ConfluenceSnapshotComment.page_id == page_id,
        ).order_by(ConfluenceSnapshotComment.created_at)
    )
    return list(result.scalars())


async def attachments(
    session: AsyncSession, snapshot_id: uuid.UUID, page_id: str
) -> list[ConfluenceSnapshotAttachment]:
    result = await session.execute(
        select(ConfluenceSnapshotAttachment).where(
            ConfluenceSnapshotAttachment.snapshot_id == snapshot_id,
            ConfluenceSnapshotAttachment.page_id == page_id,
        )
    )
    return list(result.scalars())


def attachment_file(snapshot_id: uuid.UUID, row: ConfluenceSnapshotAttachment):
    """The path this attachment's bytes live at, inside the snapshot package."""
    from . import package

    return package.resolve(snapshot_id, row.file_path)
