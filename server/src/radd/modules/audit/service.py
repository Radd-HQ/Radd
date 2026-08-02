import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz, service as auth
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.events import service as events

from .schemas import AuditActor, AuditEntry


async def audit_log(
    session: AsyncSession,
    *,
    actor: User,
    entity_type: str | None = None,
    event_types: Sequence[str] | None = None,
    actor_id: uuid.UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditEntry]:
    """Filtered, newest-first audit trail. Spec 86: one global scope — the gate
    is GLOBAL_MANAGE (admins only: instance_role admin). Instance-wide by design.
    """
    await authz.require(session, actor, Permission.GLOBAL_MANAGE)

    rows = await events.query_events(
        session,
        entity_type=entity_type,
        event_types=event_types,
        actor_id=actor_id,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )
    users = await auth.users_by_ids(session, {row.actor_id for row in rows if row.actor_id})
    entries: list[AuditEntry] = []
    for row in rows:
        user = users.get(row.actor_id) if row.actor_id else None
        payload = row.payload or {}
        entries.append(
            AuditEntry(
                id=row.id,
                at=row.created_at,
                actor=AuditActor(id=user.id, name=user.name, email=user.email) if user else None,
                event_type=str(row.event_type),
                entity_type=str(row.entity_type),
                entity_id=row.entity_id,
                changes=payload.get("changes"),
            )
        )
    return entries
