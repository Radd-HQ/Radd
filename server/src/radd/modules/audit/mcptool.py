"""The `audit_log` MCP tool (spec 123, RADD-1172): who changed what, from what,
to what — over the same ledger, through the same service, as the REST route.

The spec is the annotation (RADD-640): `permission="project.manage"` with
`project_param="project_key"` is exactly the audit access rule — the atom
on the named project, or the GLOBAL atom (an instance admin) when no
project is named — so the dispatcher enforces it before this handler runs,
and `visible_catalog` hides the tool from a key that manages no project.
This module contains no authz call on purpose.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.modules.auth import service as auth
from radd.modules.auth.types import AuthEntity
from radd.modules.events.types import EventSource
from radd.modules.items import service as items
from radd.modules.items.enums import ItemEntity
from radd.modules.projects import service as projects_service
from radd.sdk import McpToolSpec

from . import service

_LIMIT_DEFAULT = 25
_LIMIT_MAX = 100


async def _audit_log(session: AsyncSession, actor: Any, args: Mapping[str, Any]) -> Any:
    project = (
        await projects_service.get_by_key(session, str(args["project_key"]).upper())
        if args.get("project_key")
        else None
    )
    entity_type = args.get("entity_type")
    entity_id = args.get("entity_id")
    if args.get("entity_key"):
        # An item key resolves to its id; the read is gated on the item the
        # way the REST route's caller would be (item.read on its project).
        item = await items.get_item_by_key(session, str(args["entity_key"]), actor)
        entity_type, entity_id = ItemEntity.ITEM.value, str(item.id)
    actor_id = None
    if args.get("actor_email"):
        user = await auth.get_user_by_email(session, str(args["actor_email"]))
        if user is None:
            raise NotFoundError(AuthEntity.USER, str(args["actor_email"]))
        actor_id = user.id
    entries = await service.audit_log(
        session,
        actor=actor,
        project_id=project.id if project else None,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        changed_field=args.get("changed_field"),
        source=EventSource(args["source"]) if args.get("source") else None,
        start=datetime.fromisoformat(args["since"]) if args.get("since") else None,
        end=datetime.fromisoformat(args["until"]) if args.get("until") else None,
        q=args.get("q"),
        include_noise=bool(args.get("include_noise", False)),
        limit=min(int(args.get("limit", _LIMIT_DEFAULT)), _LIMIT_MAX),
        offset=int(args.get("offset", 0)),
    )
    return {
        "entries": [
            {
                "id": e.id,
                "at": e.at.isoformat(),
                "actor": e.actor.name if e.actor else None,
                "actor_email": e.actor.email if e.actor else None,
                "event": e.event_type,
                "label": e.event_label,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "entity": e.entity_label,
                "project": e.project.key if e.project else None,
                "automated": e.automated,
                "changes": e.changes or [],
            }
            for e in entries
        ],
        "count": len(entries),
    }


AUDIT_LOG = McpToolSpec(
    name="audit_log",
    description=(
        "The audit trail: who changed what, from what, to what — newest first. "
        "An instance admin reads the whole instance; anyone else must name a "
        "project they manage. Filter by entity (type + id, or an issue key), "
        "person, changed field, source, dates and free text."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_key": {
                "type": "string",
                "description": "Constrain to one project (required unless you are an instance admin).",
            },
            "entity_type": {
                "type": "string",
                "description": "Entity type, or several comma-separated: item, role, field, setting…",
            },
            "entity_id": {"type": "string", "description": "One entity's id (with entity_type)."},
            "entity_key": {"type": "string", "description": "An issue key, e.g. RADD-123."},
            "actor_email": {"type": "string", "description": "Only changes made by this person."},
            "changed_field": {
                "type": "string",
                "description": "Only rows whose diff touched this field (assignee, permissions…).",
            },
            "source": {"type": "string", "enum": ["people", "automations", "system"]},
            "since": {"type": "string", "description": "ISO 8601 lower bound."},
            "until": {"type": "string", "description": "ISO 8601 upper bound."},
            "q": {"type": "string", "description": "Free text over the event, entity and values."},
            "include_noise": {"type": "boolean", "description": "Include machine noise (default false)."},
            "limit": {"type": "integer", "minimum": 1, "maximum": _LIMIT_MAX},
            "offset": {"type": "integer", "minimum": 0},
        },
        "additionalProperties": False,
    },
    handler=_audit_log,
    permission="project.manage",
    project_scoped=True,
    project_param="project_key",
)
