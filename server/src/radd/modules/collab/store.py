"""Persistence for a room's document (spec 122): one upsert, one read, one
delete over `page_collab_docs`. Every call opens its own short session — the
room runs outside any request."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from radd.clock import utcnow
from radd.db import SessionLocal

from .models import PageCollabDoc


async def load(page_id: uuid.UUID) -> tuple[bytes, int] | None:
    """(state, page_version) or None."""
    async with SessionLocal() as session:
        row = (
            await session.execute(select(PageCollabDoc).where(PageCollabDoc.page_id == page_id))
        ).scalar_one_or_none()
        return None if row is None else (bytes(row.state), row.page_version)


async def save(page_id: uuid.UUID, state: bytes, page_version: int) -> None:
    async with SessionLocal() as session:
        stmt = insert(PageCollabDoc).values(
            page_id=page_id, state=state, page_version=page_version, updated_at=utcnow()
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[PageCollabDoc.page_id],
            set_={"state": state, "page_version": page_version, "updated_at": utcnow()},
        )
        await session.execute(stmt)
        await session.commit()


async def discard(page_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(PageCollabDoc).where(PageCollabDoc.page_id == page_id))
        await session.commit()
