"""Explicit grant deltas for an owner-module sharing transaction."""

from sqlalchemy import select

from radd.exceptions import ConflictError

from . import service
from .models import AccessGrant
from .registry import get_spec
from .schemas import SharedGrantEdits
from .types import AccessEntity, AccessEvent


async def apply_edits(session, resource_type: str, resource_id: str,
                      data: SharedGrantEdits, *, actor_id):
    await service.lock_resource(session, resource_type, resource_id)
    spec = get_spec(resource_type)
    if spec is None or not spec.hierarchical or spec.project_scoped:
        raise ConflictError(AccessEntity.GRANT, reason="not an unscoped sharing resource")
    ids = [change.id for change in data.changes]
    if len(set(ids)) != len(ids):
        raise ConflictError(AccessEntity.GRANT, reason="a grant can only be edited once")
    rows = {row.id: row for row in (await session.scalars(
        select(AccessGrant).where(AccessGrant.id.in_(ids),
            AccessGrant.resource_type == resource_type, AccessGrant.resource_id == resource_id)
        .execution_options(populate_existing=True)
    )).all()} if ids else {}
    for change in data.changes:
        row = rows.get(change.id)
        expected_expiry = (change.expected_expires_at.replace(tzinfo=None)
                           if change.expected_expires_at else None)
        if (row is None or row.access != change.expected_access
                or row.effect != change.expected_effect or row.expires_at != expected_expiry
                or row.project_id is not None):
            raise ConflictError(AccessEntity.GRANT,
                                reason="sharing changed since this draft was opened; review it again")
        if change.access is not None and change.access not in spec.accesses:
            raise ConflictError(AccessEntity.GRANT, reason=f"unknown access '{change.access}'")
    # Remove first, then edit, then add. Unmentioned rows (including expired and
    # denied grants) are never inferred to be deletions from a partial directory.
    for change in data.changes:
        if change.access is None:
            await service.remove_grant(session, change.id, actor_id=actor_id)
    for change in data.changes:
        if change.access is None or change.access == change.expected_access:
            continue
        row = rows[change.id]
        duplicate = await session.scalar(select(AccessGrant.id).where(
            AccessGrant.resource_type == resource_type, AccessGrant.resource_id == resource_id,
            AccessGrant.subject_type == row.subject_type, AccessGrant.subject_id == row.subject_id,
            AccessGrant.project_id.is_(None), AccessGrant.access == change.access,
            AccessGrant.id != row.id,
        ))
        if duplicate is not None:
            raise ConflictError(AccessEntity.GRANT, reason="that grant already exists")
        await service._emit(session, AccessEvent.REVOKED, row, actor_id)
        row.access = change.access
        await session.flush()
        await service._emit(session, AccessEvent.GRANTED, row, actor_id)
    for entry in data.additions:
        await service.add_grant(session, resource_type, resource_id,
            subject_type=entry.subject_type, subject_id=entry.subject_id, access=entry.access,
            effect=entry.effect,
            expires_at=entry.expires_at.replace(tzinfo=None) if entry.expires_at else None,
            actor_id=actor_id)
