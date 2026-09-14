"""The audit trail as a queryable ledger (spec 123).

One read path for the REST route and the MCP tool: access, noise exclusion
and per-actor redaction happen here, so the two surfaces cannot disagree.
"""

import re
import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ForbiddenError
from radd.kernel import registries
from radd.modules.auth import authz, service as auth
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.auth.principals import is_instance_admin
from radd.modules.events import service as events
from radd.modules.events.types import EventSource
from radd.modules.items import history as item_history
from radd.modules.items.enums import ItemEntity
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from .schemas import (
    AuditActor,
    AuditCatalog,
    AuditEntityType,
    AuditEntry,
    AuditEventType,
    AuditProject,
)


async def require_audit_scope(
    session: AsyncSession, actor: User, project_id: uuid.UUID | None
) -> Project | None:
    """Who may read what (spec 123). An instance admin reads everything; anyone
    else reads ONE project's trail, and only where they hold `project.manage`.
    Returns the project the read is constrained to, or None for the global view."""
    if project_id is None:
        if not is_instance_admin(actor):
            raise ForbiddenError(
                "the instance-wide audit log requires an instance admin — "
                "pass project_id to read a project you manage"
            )
        return None
    project = await projects_service.get_project(session, project_id)
    if not is_instance_admin(actor):
        await authz.require(session, actor, Permission.PROJECT_MANAGE, project=project)
    return project


def noise_event_types() -> list[str]:
    """Event types the registry marks `audited=False` — hidden unless asked for."""
    return [str(key) for key, spec in registries.event_types.items() if not spec.audited]


async def audit_log(
    session: AsyncSession,
    *,
    actor: User,
    project_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    event_types: Sequence[str] | None = None,
    actor_id: uuid.UUID | None = None,
    changed_field: str | None = None,
    source: EventSource | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    q: str | None = None,
    include_noise: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditEntry]:
    """Filtered, newest-first audit trail, constrained to what `actor` may read."""
    project = await require_audit_scope(session, actor, project_id)
    rows = await events.query_events(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        event_types=event_types,
        exclude_event_types=None if include_noise else noise_event_types(),
        actor_id=actor_id,
        project_id=project.id if project is not None else None,
        changed_field=changed_field,
        source=source,
        start=start,
        end=end,
        q=q,
        limit=limit,
        offset=offset,
    )
    users = await auth.users_by_ids(session, {row.actor_id for row in rows if row.actor_id})
    projects = await _projects_by_id(session, {row.project_id for row in rows if row.project_id})
    # RADD-834: a project manager who cannot read a restricted field sees
    # "changed", never the value — the same seam the History tab uses. An
    # instance admin holds everything, so the lookup is skipped.
    redaction = (
        None
        if is_instance_admin(actor) or project is None
        else await item_history.redaction_for(session, actor, project)
    )
    entries: list[AuditEntry] = []
    for row in rows:
        user = users.get(row.actor_id) if row.actor_id else None
        payload = row.payload or {}
        spec = registries.event_types.get(row.event_type)
        changes = payload.get("changes")
        if changes is not None and redaction is not None and row.entity_type == ItemEntity.ITEM:
            changes = item_history.redact_changes(changes, *redaction)
        entries.append(
            AuditEntry(
                id=row.id,
                at=row.created_at,
                actor=AuditActor(id=user.id, name=user.name, email=user.email) if user else None,
                event_type=str(row.event_type),
                event_label=spec.label if spec else humanize(row.event_type),
                event_group=spec.group if spec else "Other",
                entity_type=str(row.entity_type),
                entity_id=row.entity_id,
                entity_label=row.entity_label,
                refs={
                    key: value
                    for key, value in payload.items()
                    if key in registries.entity_refs and isinstance(value, dict)
                },
                project=projects.get(row.project_id) if row.project_id else None,
                automated=row.automated,
                silent=row.silent,
                changes=changes,
            )
        )
    return entries


async def _projects_by_id(
    session: AsyncSession, ids: set[uuid.UUID]
) -> dict[uuid.UUID, AuditProject]:
    if not ids:
        return {}
    return {
        p.id: AuditProject(id=p.id, key=p.key, name=p.name)
        for p in await projects_service.list_projects(session)
        if p.id in ids
    }


def humanize(key: str) -> str:
    """`storage_host` → `Storage host`; `item.updated` → `Item updated`."""
    words = re.split(r"[._]+", key.strip())
    return " ".join(words).capitalize() if words else key


def catalog() -> AuditCatalog:
    """The registry as the SPA's filter vocabulary (spec 123)."""
    event_types: list[AuditEventType] = []
    entity_keys: set[str] = set(registries.entity_refs)
    for key, spec in sorted(registries.event_types.items(), key=lambda kv: str(kv[0])):
        entity_type = spec.entity_type or str(key).split(".", 1)[0]
        entity_keys.add(entity_type)
        event_types.append(
            AuditEventType(
                event_type=str(key),
                label=spec.label,
                group=spec.group,
                entity_type=entity_type,
                has_changes=spec.has_changes,
                audited=spec.audited,
            )
        )
    entity_types = [
        AuditEntityType(
            key=key,
            label=(
                registries.entity_refs[key].label
                if key in registries.entity_refs and registries.entity_refs[key].label
                else humanize(key)
            ),
        )
        for key in sorted(entity_keys)
    ]
    return AuditCatalog(event_types=event_types, entity_types=entity_types)
