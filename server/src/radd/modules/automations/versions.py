"""Automation versions (RADD-1268): writing, reading and restoring.

Kept beside `runs.py` for the same reason it is: the graph's CRUD is one
concern, and what a save leaves behind is another.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.clock import utcnow
from radd.exceptions import NotFoundError

from .models import Automation, AutomationVersion

#: What a version snapshots. `enabled` and `position` are deliberately NOT in
#: it: toggling an automation off is not a new version of what it is, and
#: reordering the list is nobody's history.
VERSIONED_FIELDS: tuple[str, ...] = ("name", "nodes", "edges", "orientation")


def content_of(rule: Automation) -> dict:
    return {field: getattr(rule, field) for field in VERSIONED_FIELDS}


def changed(rule: Automation, before: dict) -> bool:
    """Did anything a version snapshots change since `before` (a `content_of`)?"""
    return any(getattr(rule, field) != before.get(field) for field in VERSIONED_FIELDS)


async def write(
    session: AsyncSession,
    rule: Automation,
    *,
    actor_id: uuid.UUID | None,
    note: str = "",
    restored_from: int | None = None,
) -> AutomationVersion:
    """Snapshot the rule's CURRENT content as the next version and move the
    pointer. The caller has already changed the rule; this records it."""
    rule.version = (rule.version or 0) + 1
    row = AutomationVersion(
        automation_id=rule.id,
        version=rule.version,
        created_by_id=actor_id,
        created_at=utcnow(),
        note=(note or "")[:2000],
        restored_from=restored_from,
        **content_of(rule),
    )
    session.add(row)
    await session.flush()
    return row


async def list_versions(session: AsyncSession, automation_id: uuid.UUID) -> list[AutomationVersion]:
    """Newest first."""
    return list(
        (
            await session.execute(
                select(AutomationVersion)
                .where(AutomationVersion.automation_id == automation_id)
                .order_by(AutomationVersion.version.desc())
            )
        ).scalars()
    )


async def get_version(session: AsyncSession, automation_id: uuid.UUID, version: int) -> AutomationVersion:
    row = (
        await session.execute(
            select(AutomationVersion).where(
                AutomationVersion.automation_id == automation_id, AutomationVersion.version == version
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("automation_version", f"{automation_id}/v{version}")
    return row
