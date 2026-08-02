"""Server-side logic for acme-notes — an aggregate the CLIENT couldn't compute on its own (the UI
only ever holds the notes for the issue it's looking at; this counts across the whole project).

It reaches the plugin's OWN auto-wired table through the public SDK (`entities.model_for`) and the
kernel-provided session — no raw Base/engine access.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.sdk import entities


async def recent_notes(session: AsyncSession, limit: int) -> list[dict]:
    """The N most recent notes across the instance — powers the 'Most Recent Notes' dashboard widget.
    A server-ordered query (the browser can't cheaply do 'most recent across every issue')."""
    Note = entities.model_for("note")
    if Note is None:
        return []
    rows = (
        await session.execute(select(Note).order_by(Note.created_at.desc()).limit(limit))
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "item_id": str(r.item_id) if r.item_id else None,
            "body": r.body,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def notes_stats(session: AsyncSession, project_id: uuid.UUID | None) -> dict:
    Note = entities.model_for("note")
    if Note is None:  # entity not registered (plugin disabled) — nothing to report
        return {"total": 0, "items_with_notes": 0, "top_item_id": None, "top_item_count": 0}

    def scoped(stmt):
        return stmt.where(Note.project_id == project_id) if project_id else stmt

    total = (await session.execute(scoped(select(func.count()).select_from(Note)))).scalar_one()
    items_with_notes = (
        await session.execute(
            scoped(select(func.count(func.distinct(Note.item_id))).where(Note.item_id.isnot(None)))
        )
    ).scalar_one()
    top = (
        await session.execute(
            scoped(
                select(Note.item_id, func.count().label("c"))
                .where(Note.item_id.isnot(None))
                .group_by(Note.item_id)
                .order_by(func.count().desc())
                .limit(1)
            )
        )
    ).first()

    return {
        "total": int(total or 0),
        "items_with_notes": int(items_with_notes or 0),
        "top_item_id": str(top[0]) if top else None,
        "top_item_count": int(top[1]) if top else 0,
    }
