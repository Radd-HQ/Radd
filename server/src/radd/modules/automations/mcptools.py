"""Automations over MCP (RADD-1271).

RADD-1270 created this project's three dogfood automations over REST with a
hand-written script, because the MCP catalog exposed nothing about them: an
agent could not list what exists, read a graph, create or edit one, dry-run
it, or read its run history or versions. Every REST fallback is an MCP gap
(the working agreement); this closes the one the automation wave took.

Each tool is the REST route's twin — same service call, same atom, same
shape. Reads and the dry run want `automation.manage` (global, the REST
gate); create/update want the CRUD atoms `automation.manage` implies; the
manual run wants `item.update` on the ITEM's project, because manual rules
are curated by admins precisely so members may invoke them (the router's
own argument). The kernel enforces the global atoms before a handler runs;
`run_automation` enforces in-handler, like the route it mirrors.

An automation is addressed by id OR by its exact name (case-insensitive):
an agent that just listed holds both, and the one it read off a screen is
the name. Names are not unique, so an ambiguous name is refused with the
candidate ids rather than resolved to whichever came first.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.kernel.mcptools import limit_arg, limit_property, object_schema
from radd.kernel.specs import McpToolSpec
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.auth.types import Permission
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from . import catalog_read, engine, runs, service, versions
from .models import Automation
from .schemas import RuleCreate, RuleRead, RuleTestResult, RuleUpdate, RunDetailRead, RunRead
from .types import (
    MAX_GRAPH_EDGES,
    MAX_GRAPH_NODES,
    AutomationEntity,
    AutomationNodeKind,
    GraphOrientation,
    NodePort,
)

_MANAGE = Permission.AUTOMATION_MANAGE

_AUTOMATION = {
    "type": "string",
    "description": "The automation's id, or its exact name (case-insensitive).",
    "maxLength": 200,
}
_NOTE = {
    "type": "string",
    "description": "Why this change — recorded on the version it writes.",
    "maxLength": 2000,
}
_NODE = object_schema(
    {
        "id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "description": "Unique within the graph; edges name it.",
        },
        "kind": {"type": "string", "enum": [kind.value for kind in AutomationNodeKind]},
        "type": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100,
            "description": "The node type: trigger.event, filter.slq, gate.field_changed, "
            "action.add_comment, search.slq, … — automation_catalog lists the "
            "contributed ones.",
        },
        "params": {
            "type": "object",
            "description": "What this node type takes: a trigger {event, schedule?}, "
            "a filter {slq}, an action its own fields.",
        },
        "name": {
            "type": "string",
            "maxLength": 30,
            "description": "What downstream template tokens call this node ({{name.field}}).",
        },
        "x": {"type": "number"},
        "y": {"type": "number"},
    },
    ["id", "kind", "type"],
)
_EDGE = object_schema(
    {
        "source": {"type": "string", "minLength": 1, "maxLength": 64},
        "port": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "default": NodePort.OUT.value,
            "description": "The source node's output port: out, matched/unmatched "
            "(filters), true/false (gates), or a contributed node's own.",
        },
        "target": {"type": "string", "minLength": 1, "maxLength": 64},
    },
    ["source", "target"],
)
_NODES = {"type": "array", "items": _NODE, "minItems": 1, "maxItems": MAX_GRAPH_NODES}
_EDGES = {"type": "array", "items": _EDGE, "maxItems": MAX_GRAPH_EDGES}
_ORIENTATION = {
    "type": "string",
    "enum": [orientation.value for orientation in GraphOrientation],
    "description": "How the canvas lays the graph out; the engine ignores it.",
}
_VERSION = {
    "type": "integer",
    "minimum": 1,
    "description": "A version number from list_automation_versions.",
}
_KEY = {"type": "string", "description": "Item key, e.g. TD-42."}


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


async def _resolve(session: AsyncSession, ref: Any) -> Automation:
    """By id, else by exact name — refusing an ambiguous name with the ids."""
    text = str(ref).strip()
    try:
        return await service.get_rule(session, uuid.UUID(text))
    except ValueError:
        pass
    wanted = text.casefold()
    matches = [rule for rule in await service.list_rules(session) if rule.name.casefold() == wanted]
    if not matches:
        raise NotFoundError(AutomationEntity.RULE, text)
    if len(matches) > 1:
        ids = ", ".join(str(rule.id) for rule in matches)
        raise ConflictError(
            AutomationEntity.RULE,
            reason=f"{len(matches)} automations are named {text!r}; address one by id ({ids})",
        )
    return matches[0]


def _summary(read: RuleRead) -> dict[str, Any]:
    """The list row: what it is, when it fires, what happened last — never the graph."""
    return {
        "id": str(read.id),
        "name": read.name,
        "enabled": read.enabled,
        "version": read.version,
        "node_count": len(read.nodes),
        "triggers": [_dump(trigger) for trigger in read.triggers],
        "last_run_at": read.last_run_at.isoformat() if read.last_run_at else None,
        "last_run_status": read.last_run_status,
        "updated_at": read.updated_at.isoformat(),
    }


async def _summary_of(session: AsyncSession, rule: Automation) -> dict[str, Any]:
    return _summary((await service.rule_reads(session, [rule]))[0])


def _graph(read: RuleRead) -> dict[str, Any]:
    return {**_summary(read), "orientation": read.orientation, "nodes": read.nodes, "edges": read.edges}


# --- handlers ---


async def _automation_catalog(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    return _dump(await catalog_read.build(session, actor))


async def _list_automations(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    reads = await service.rule_reads(session, await service.list_rules(session))
    return {"automations": [_summary(read) for read in reads], "count": len(reads)}


async def _get_automation(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    rule = await _resolve(session, args["automation"])
    return _graph((await service.rule_reads(session, [rule]))[0])


async def _create_automation(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    # A payload RuleCreate refuses is a pydantic ValidationError — a ValueError,
    # which the MCP router already shapes into an `isError` tool result.
    rule = await service.create_rule(session, RuleCreate.model_validate(dict(args)), actor_id=actor.id)
    return {"created": await _summary_of(session, rule)}


_UPDATABLE = ("name", "enabled", "position", "orientation", "nodes", "edges", "note")


async def _update_automation(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    rule = await _resolve(session, args["automation"])
    data = RuleUpdate.model_validate({key: args[key] for key in _UPDATABLE if key in args})
    rule = await service.update_rule(session, rule.id, data, actor_id=actor.id)
    return {"updated": await _summary_of(session, rule)}


async def _dry_run_automation(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    rule = await _resolve(session, args["automation"])
    item_id = None
    if args.get("key"):
        item_id = (await items_service.get_item_by_key(session, str(args["key"]), actor=actor)).id
    return _dump(await engine.preview(session, rule, item_id, args.get("trigger_node_id")))


async def _run_automation(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    rule = await _resolve(session, args["automation"])
    node_id = await service.manual_trigger_node(session, rule.id)
    if node_id is None:
        raise ConflictError(
            AutomationEntity.RULE, reason="only automations with a manual trigger can be run directly"
        )
    if not rule.enabled:
        raise ConflictError(AutomationEntity.RULE, reason="rule is disabled")
    read = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    item = await items_service.require_item(session, read.id)
    project = await projects_service.get_project(session, item.project_id)
    await authz.require(session, actor, Permission.ITEM_UPDATE, project=project)
    ran = await engine.run_manual(session, rule, item.id, start_node_id=node_id)
    return {"automation": str(rule.id), "name": rule.name, "key": read.key, "ran": ran}


async def _list_automation_runs(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    rule = await _resolve(session, args["automation"])
    before = datetime.fromisoformat(str(args["before"])) if args.get("before") else None
    rows = await runs.list_runs(session, rule.id, limit=limit_arg(args), before=before)
    return {
        "automation": str(rule.id),
        "runs": [_dump(RunRead.model_validate(row)) for row in rows],
        "count": len(rows),
    }


async def _get_automation_run(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    rule = await _resolve(session, args["automation"])
    row = await runs.get_run(session, rule.id, uuid.UUID(str(args["run_id"])))
    read = RunDetailRead.model_validate(row)
    read.report = RuleTestResult.model_validate(row.report) if row.report else None
    return _dump(read)


async def _list_automation_versions(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    rule = await _resolve(session, args["automation"])
    reads = await service.version_reads(session, await versions.list_versions(session, rule.id))
    return {
        "automation": str(rule.id),
        "current": rule.version,
        "versions": [_dump(read) for read in reads],
    }


async def _get_automation_version(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    rule = await _resolve(session, args["automation"])
    row = await versions.get_version(session, rule.id, int(args["version"]))
    read = (await service.version_reads(session, [row]))[0]
    return {
        **_dump(read),
        "current": row.version == rule.version,
        "orientation": row.orientation,
        "nodes": row.nodes or [],
        "edges": row.edges or [],
    }


async def _restore_automation_version(
    session: AsyncSession, actor: User, args: Mapping[str, Any]
) -> Any:
    rule = await _resolve(session, args["automation"])
    version = int(args["version"])
    rule = await service.restore_version(
        session, rule.id, version, actor.id, note=str(args.get("note") or "")
    )
    return {"restored_from": version, "automation": await _summary_of(session, rule)}


# --- the specs ---

AUTOMATION_CATALOG = McpToolSpec(
    name="automation_catalog",
    description="What this instance's automations can be built from: every trigger "
    "event, the schedule kinds, the nodes plugins contribute (with their params "
    "schema and ports), each node type's arity options and outputs, and the "
    "template tokens. Read it before writing a graph.",
    input_schema=object_schema({}),
    handler=_automation_catalog,
    permission=_MANAGE,
)

LIST_AUTOMATIONS = McpToolSpec(
    name="list_automations",
    description="Every automation on the instance — name, enabled, version, its "
    "triggers with their next/last scheduled run, and the newest recorded run. "
    "Graphs are not included; get_automation has them.",
    input_schema=object_schema({}),
    handler=_list_automations,
    permission=_MANAGE,
)

GET_AUTOMATION = McpToolSpec(
    name="get_automation",
    description="One automation with its whole graph (nodes, edges, orientation), by id or name.",
    input_schema=object_schema({"automation": _AUTOMATION}, ["automation"]),
    handler=_get_automation,
    permission=_MANAGE,
)

CREATE_AUTOMATION = McpToolSpec(
    name="create_automation",
    description="Create an automation from a graph. Validated exactly as the editor's "
    "Save: every node type must exist, filters' SLQ must compile, every edge must "
    "name a port its source emits. Answers with a receipt, not the graph.",
    input_schema=object_schema(
        {
            "name": {"type": "string", "minLength": 1, "maxLength": 200},
            "nodes": _NODES,
            "edges": _EDGES,
            "enabled": {"type": "boolean", "default": True},
            "orientation": _ORIENTATION,
            "note": _NOTE,
        },
        ["name", "nodes"],
    ),
    handler=_create_automation,
    permission=Permission.AUTOMATION_CREATE,
)

UPDATE_AUTOMATION = McpToolSpec(
    name="update_automation",
    description="Rename, enable/disable, reorder or replace the graph of an "
    "automation. The graph is replaced whole: pass nodes AND edges together. A "
    "content change writes a new version; a toggle does not.",
    input_schema=object_schema(
        {
            "automation": _AUTOMATION,
            "name": {"type": "string", "minLength": 1, "maxLength": 200},
            "enabled": {"type": "boolean"},
            "position": {"type": "integer", "minimum": 0},
            "orientation": _ORIENTATION,
            "nodes": _NODES,
            "edges": _EDGES,
            "note": _NOTE,
        },
        ["automation"],
    ),
    handler=_update_automation,
    permission=Permission.AUTOMATION_UPDATE,
)

DRY_RUN_AUTOMATION = McpToolSpec(
    name="dry_run_automation",
    description="Walk the graph with the actions off and report, per node, what "
    "arrived and what left by each port, plus the actions it would have taken — "
    "the editor's Dry run. `key` seeds the walk with an item; omit it for a graph "
    "fed by a schedule or a search node. Writes nothing and records no run.",
    input_schema=object_schema(
        {
            "automation": _AUTOMATION,
            "key": {**_KEY, "description": "An item key to seed the walk with, e.g. TD-42."},
            "trigger_node_id": {
                "type": "string",
                "maxLength": 64,
                "description": "Start at this trigger node when the graph has several.",
            },
        },
        ["automation"],
    ),
    handler=_dry_run_automation,
    permission=_MANAGE,
)

RUN_AUTOMATION = McpToolSpec(
    name="run_automation",
    description="Run an automation that has a MANUAL trigger on one item — the "
    "editor's slash-menu quick action. This WRITES; it needs item.update on the "
    "item's project, not automation.manage.",
    input_schema=object_schema({"automation": _AUTOMATION, "key": _KEY}, ["automation", "key"]),
    handler=_run_automation,
    permission=Permission.ITEM_UPDATE,
    project_scoped=True,
    kernel_enforced=False,
)

LIST_AUTOMATION_RUNS = McpToolSpec(
    name="list_automation_runs",
    description="Recorded runs of an automation, newest first: when, what started "
    "it, which items, how many actions applied or were skipped, and the status "
    "(applied, nothing_to_do, refused, failed). `before` pages by started_at.",
    input_schema=object_schema(
        {
            "automation": _AUTOMATION,
            "limit": limit_property(),
            "before": {
                "type": "string",
                "format": "date-time",
                "description": "Only runs started before this ISO timestamp.",
            },
        },
        ["automation"],
    ),
    handler=_list_automation_runs,
    permission=_MANAGE,
)

GET_AUTOMATION_RUN = McpToolSpec(
    name="get_automation_run",
    description="One recorded run with its whole report — the dry run's shape, "
    "as it actually happened.",
    input_schema=object_schema(
        {"automation": _AUTOMATION, "run_id": {"type": "string", "format": "uuid"}},
        ["automation", "run_id"],
    ),
    handler=_get_automation_run,
    permission=_MANAGE,
)

LIST_AUTOMATION_VERSIONS = McpToolSpec(
    name="list_automation_versions",
    description="Every version of an automation, newest first, with author, note "
    "and what it was restored from. The current version is included.",
    input_schema=object_schema({"automation": _AUTOMATION}, ["automation"]),
    handler=_list_automation_versions,
    permission=_MANAGE,
)

GET_AUTOMATION_VERSION = McpToolSpec(
    name="get_automation_version",
    description="One version's graph, read-only — what restoring it would bring back.",
    input_schema=object_schema(
        {"automation": _AUTOMATION, "version": _VERSION}, ["automation", "version"]
    ),
    handler=_get_automation_version,
    permission=_MANAGE,
)

RESTORE_AUTOMATION_VERSION = McpToolSpec(
    name="restore_automation_version",
    description="Make an old version current by writing a NEW version that copies "
    "it (history never rewrites). The copied graph is re-validated first.",
    input_schema=object_schema(
        {"automation": _AUTOMATION, "version": _VERSION, "note": _NOTE},
        ["automation", "version"],
    ),
    handler=_restore_automation_version,
    permission=_MANAGE,
)

MCP_TOOLS = (
    AUTOMATION_CATALOG,
    LIST_AUTOMATIONS,
    GET_AUTOMATION,
    CREATE_AUTOMATION,
    UPDATE_AUTOMATION,
    DRY_RUN_AUTOMATION,
    RUN_AUTOMATION,
    LIST_AUTOMATION_RUNS,
    GET_AUTOMATION_RUN,
    LIST_AUTOMATION_VERSIONS,
    GET_AUTOMATION_VERSION,
    RESTORE_AUTOMATION_VERSION,
)
