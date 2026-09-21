"""Automations over MCP (RADD-1271): the three dogfood graphs RADD-1270 had to
create over REST are recreated here through the MCP dispatcher with zero REST
— list, get, create, update, dry-run, run, runs, versions, restore — and the
dry run answers with exactly what `engine.preview` (the editor's Dry run)
answers.

DB-backed, flushed never committed.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.kernel import registries
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.automations import engine
from radd.modules.automations.mcptools import MCP_TOOLS
from radd.modules.automations.types import AutomationTrigger, RunSource, RunStatus
from radd.modules.items import service as items
from radd.modules.items.enums import ItemEvent
from radd.modules.items.schemas import ItemCreate
from radd.modules.mcp import tools
from radd.modules.mcp.catalog import registry_catalog
from radd.modules.mcp.requirements import visible_catalog
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.releases.types import ReleaseEvent

TOOL_NAMES = {spec.name for spec in MCP_TOOLS}


@pytest.fixture
async def db():
    engine_ = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine_, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine_.dispose()


async def _user(db, role: InstanceRole) -> User:
    user = User(
        email=f"mcpauto-{uuid.uuid4().hex[:8]}@example.com", name="MCP Automations", instance_role=role.value
    )
    db.add(user)
    await db.flush()
    return user


async def _project(db):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"MA{uuid.uuid4().hex[:4].upper()}", name="MCP automations")
    )


# The RADD project's three dogfood automations (RADD-1270), shape for shape.
# Only the values that must exist in a throwaway database are substituted:
# the project key and the person's email.


def _triage_arrival(project_key: str, email: str) -> dict:
    return {
        "name": "Triage arrival",
        "nodes": [
            {"id": "trg1", "kind": "trigger", "type": "trigger.event", "params": {"event": ItemEvent.CREATED.value}},
            {"id": "flt_radd", "kind": "filter", "type": "filter.slq", "params": {"slq": f"project = {project_key}"}},
            {"id": "flt_unassigned", "kind": "filter", "type": "filter.slq", "params": {"slq": "assignee = none"}},
            {"id": "assign", "kind": "action", "type": "action.set_assignee", "params": {"assignee": email}},
            {"id": "label", "kind": "action", "type": "action.add_label", "params": {"label": "triage"}},
            {"id": "not_me", "kind": "gate", "type": "gate.changed_by", "params": {"users": [email], "negate": True}},
            {
                "id": "thanks",
                "kind": "action",
                "type": "action.add_comment",
                "params": {"body": "Thanks for filing this.", "visibility": "public"},
            },
        ],
        "edges": [
            {"source": "trg1", "port": "out", "target": "flt_radd"},
            {"source": "flt_radd", "port": "matched", "target": "flt_unassigned"},
            {"source": "flt_unassigned", "port": "matched", "target": "assign"},
            {"source": "assign", "port": "out", "target": "label"},
            {"source": "flt_radd", "port": "matched", "target": "not_me"},
            {"source": "not_me", "port": "true", "target": "thanks"},
        ],
    }


def _release_receipt(email: str) -> dict:
    return {
        "name": "Release shipped receipt",
        "nodes": [
            {"id": "trg1", "kind": "trigger", "type": "trigger.event", "params": {"event": ReleaseEvent.UPDATED.value}},
            {
                "id": "released",
                "kind": "gate",
                "type": "gate.field_changed",
                "params": {"field": "status", "to_mode": "specific", "from_mode": "any", "to_values": ["released"], "from_values": []},
            },
            {
                "id": "tell",
                "kind": "action",
                "type": "action.notify_user",
                "params": {"user": email, "message": "{{payload.name}} ({{payload.version}}) is marked released."},
            },
        ],
        "edges": [
            {"source": "trg1", "port": "out", "target": "released"},
            {"source": "released", "port": "true", "target": "tell"},
        ],
    }


def _stale_review(project_key: str) -> dict:
    return {
        "name": "Stale review nudge",
        "nodes": [
            {
                "id": "trg1",
                "kind": "trigger",
                "type": "trigger.event",
                "params": {"event": AutomationTrigger.SCHEDULE.value, "schedule": {"kind": "weekly", "time": "09:00", "weekdays": [0]}},
            },
            {
                "id": "find_trg1",
                "kind": "source",
                "type": "search.slq",
                "params": {"slq": f"project = {project_key} AND updated < today-14d", "mode": "replace", "project": ""},
            },
            {
                "id": "nudge",
                "kind": "action",
                "type": "action.add_comment",
                "params": {"body": "This has sat for two weeks without an update.", "visibility": "public"},
            },
            {
                "id": "ping",
                "kind": "action",
                "type": "action.notify_user",
                "params": {"user": "assignee", "arity": "item", "message": "{{item.key}} is stale — {{item.title}}"},
            },
        ],
        "edges": [
            {"source": "trg1", "port": "out", "target": "find_trg1"},
            {"source": "find_trg1", "port": "out", "target": "nudge"},
            {"source": "nudge", "port": "out", "target": "ping"},
        ],
    }


def _manual(project_key: str) -> dict:
    return {
        "name": "Escalate",
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": AutomationTrigger.MANUAL.value}},
            {"id": "flt", "kind": "filter", "type": "filter.slq", "params": {"slq": f"project = {project_key}"}},
            {"id": "act", "kind": "action", "type": "action.set_priority", "params": {"priority": "high"}},
        ],
        "edges": [
            {"source": "trg", "port": "out", "target": "flt"},
            {"source": "flt", "port": "matched", "target": "act"},
        ],
    }


# --- the catalog ---


def test_the_tools_are_registered_with_closed_schemas():
    names = {tool["name"] for tool in registry_catalog(frozenset())}
    assert TOOL_NAMES <= names
    for spec in MCP_TOOLS:
        assert registries.mcp_tools[spec.name].input_schema["additionalProperties"] is False
    assert registries.mcp_tools["create_automation"].input_schema["required"] == ["name", "nodes"]


async def test_only_an_automation_manager_sees_them(db):
    """Global `automation.manage` (and the CRUD atoms it implies) is the REST gate
    for everything but the manual run; the catalog says the same."""
    catalog = registry_catalog(frozenset())  # the contributed half; these all live there
    await _project(db)  # run_automation is project-scoped: it needs somewhere to run
    admin = await _user(db, InstanceRole.ADMIN)
    admin_names = {tool["name"] for tool in await visible_catalog(db, admin, catalog)}
    assert TOOL_NAMES <= admin_names
    member = await _user(db, InstanceRole.MEMBER)
    member_names = {tool["name"] for tool in await visible_catalog(db, member, catalog)}
    assert not ((TOOL_NAMES - {"run_automation"}) & member_names)
    with pytest.raises(ForbiddenError):
        await tools.call_tool(db, member, "list_automations", {})
    with pytest.raises(ForbiddenError):
        await tools.call_tool(db, member, "create_automation", _manual("X"))


async def test_the_catalog_tool_is_the_builders_catalog(db):
    admin = await _user(db, InstanceRole.ADMIN)
    catalog = await tools.call_tool(db, admin, "automation_catalog", {})
    assert ItemEvent.CREATED.value in {trigger["event_type"] for trigger in catalog["triggers"]}
    assert catalog["schedule_trigger"] == AutomationTrigger.SCHEDULE.value
    assert {row["type"] for row in catalog["node_arity"]} >= {"action.set_state", "action.create_item"}
    assert any(token["token"].startswith("{{item.") for token in catalog["tokens"])


# --- the dogfood loop, zero REST ---


async def test_the_dogfood_automations_round_trip(db):
    admin = await _user(db, InstanceRole.ADMIN)
    project = await _project(db)

    created = [
        await tools.call_tool(db, admin, "create_automation", graph)
        for graph in (
            _triage_arrival(project.key, admin.email),
            _release_receipt(admin.email),
            _stale_review(project.key),
        )
    ]
    assert [c["created"]["version"] for c in created] == [1, 1, 1]
    assert created[0]["created"]["node_count"] == 7
    assert created[2]["created"]["triggers"][0]["event_type"] == AutomationTrigger.SCHEDULE.value
    assert created[2]["created"]["triggers"][0]["next_run_at"] is not None

    listed = await tools.call_tool(db, admin, "list_automations", {})
    by_name = {row["name"]: row for row in listed["automations"]}
    assert {"Triage arrival", "Release shipped receipt", "Stale review nudge"} <= set(by_name)
    assert "nodes" not in by_name["Triage arrival"]  # the list is rows, not graphs
    assert by_name["Release shipped receipt"]["triggers"][0]["event_type"] == ReleaseEvent.UPDATED.value

    # By name, case-insensitively, and the graph comes back whole.
    graph = await tools.call_tool(db, admin, "get_automation", {"automation": "triage ARRIVAL"})
    assert graph["id"] == created[0]["created"]["id"]
    assert [node["id"] for node in graph["nodes"]][:2] == ["trg1", "flt_radd"]
    assert {(edge["source"], edge["port"], edge["target"]) for edge in graph["edges"]} >= {
        ("not_me", "true", "thanks"), ("flt_radd", "matched", "flt_unassigned"),
    }
    with pytest.raises(NotFoundError):
        await tools.call_tool(db, admin, "get_automation", {"automation": "No such thing"})

    # The dry run over MCP IS the editor's Dry run.
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="unassigned"), admin)
    dry = await tools.call_tool(db, admin, "dry_run_automation", {"automation": "Triage arrival", "key": item.key})
    rule_id = uuid.UUID(graph["id"])
    from radd.modules.automations import service as automations

    expected = await engine.preview(db, await automations.get_rule(db, rule_id), item.id, None)
    assert dry == expected.model_dump(mode="json")
    assert dry["matched"] is True
    assert {action["type"] for action in dry["would_apply"]} >= {"set_assignee", "add_label"}
    assert (await items.require_item(db, item.id)).assignee_id is None, "a dry run writes nothing"
    assert (await tools.call_tool(db, admin, "list_automation_runs", {"automation": graph["id"]}))["count"] == 0

    # A graph the validator refuses is a tool error, not a crash.
    broken = _release_receipt(admin.email)
    broken["edges"][1]["port"] = "sideways"
    with pytest.raises(ConflictError):
        await tools.call_tool(db, admin, "create_automation", broken)


async def test_update_versions_and_restore(db):
    admin = await _user(db, InstanceRole.ADMIN)
    project = await _project(db)
    receipt = (await tools.call_tool(db, admin, "create_automation", {**_manual(project.key), "note": "first"}))["created"]
    ref = receipt["id"]

    # A toggle writes no version; a rename does; a graph replacement does.
    toggled = await tools.call_tool(db, admin, "update_automation", {"automation": ref, "enabled": False})
    assert toggled["updated"]["enabled"] is False and toggled["updated"]["version"] == 1
    renamed = await tools.call_tool(db, admin, "update_automation", {"automation": ref, "name": "Escalate now", "note": "rename"})
    assert renamed["updated"]["version"] == 2
    g2 = _manual(project.key)
    g2["nodes"][2]["params"]["priority"] = "blocker"
    replaced = await tools.call_tool(
        db, admin, "update_automation", {"automation": ref, "nodes": g2["nodes"], "edges": g2["edges"], "enabled": True}
    )
    assert replaced["updated"]["version"] == 3 and replaced["updated"]["enabled"] is True

    listed = await tools.call_tool(db, admin, "list_automation_versions", {"automation": ref})
    assert listed["current"] == 3
    assert [(v["version"], v["note"]) for v in listed["versions"]] == [(3, ""), (2, "rename"), (1, "first")]
    assert listed["versions"][0]["created_by_name"] == admin.name

    v1 = await tools.call_tool(db, admin, "get_automation_version", {"automation": ref, "version": 1})
    assert v1["current"] is False and v1["name"] == "Escalate"
    assert v1["nodes"][2]["params"]["priority"] == "high"
    with pytest.raises(NotFoundError):
        await tools.call_tool(db, admin, "get_automation_version", {"automation": ref, "version": 9})

    restored = await tools.call_tool(
        db, admin, "restore_automation_version", {"automation": ref, "version": 1, "note": "back"}
    )
    assert restored["restored_from"] == 1
    assert restored["automation"]["version"] == 4 and restored["automation"]["name"] == "Escalate"
    graph = await tools.call_tool(db, admin, "get_automation", {"automation": ref})
    assert graph["nodes"][2]["params"]["priority"] == "high"
    listed = await tools.call_tool(db, admin, "list_automation_versions", {"automation": ref})
    assert listed["versions"][0]["restored_from"] == 1 and len(listed["versions"]) == 4

    # A second automation with the same name makes the name ambiguous — refused
    # with the ids, never resolved to whichever came first.
    await tools.call_tool(db, admin, "create_automation", _manual(project.key))
    with pytest.raises(ConflictError) as refused:
        await tools.call_tool(db, admin, "get_automation", {"automation": "Escalate"})
    assert ref in str(refused.value)


async def test_a_manual_run_writes_and_is_recorded(db):
    admin = await _user(db, InstanceRole.ADMIN)
    member = await _user(db, InstanceRole.MEMBER)
    project = await _project(db)
    ref = (await tools.call_tool(db, admin, "create_automation", _manual(project.key)))["created"]["id"]
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="slow"), admin)

    # item.update on the item's project, not automation.manage: an ungranted
    # member is refused by the same gate the REST route uses.
    with pytest.raises((ForbiddenError, NotFoundError)):
        await tools.call_tool(db, member, "run_automation", {"automation": ref, "key": item.key})

    ran = await tools.call_tool(db, admin, "run_automation", {"automation": ref, "key": item.key})
    assert ran == {"automation": ref, "name": "Escalate", "key": item.key, "ran": True}
    assert (await items.require_item(db, item.id)).priority == "high"

    runs = await tools.call_tool(db, admin, "list_automation_runs", {"automation": "Escalate", "limit": 5})
    assert runs["count"] == 1
    run = runs["runs"][0]
    assert run["status"] == RunStatus.APPLIED.value and run["source"] == RunSource.MANUAL.value
    assert run["item_keys"] == [item.key] and run["actions_applied"] == 1
    detail = await tools.call_tool(db, admin, "get_automation_run", {"automation": ref, "run_id": run["id"]})
    assert detail["report"]["would_apply"][0]["node_id"] == "act"
    assert {node["node_id"] for node in detail["report"]["nodes"]} == {"trg", "flt", "act"}

    # Only a manual trigger can be run by hand.
    other = (await tools.call_tool(db, admin, "create_automation", _release_receipt(admin.email)))["created"]["id"]
    with pytest.raises(ConflictError):
        await tools.call_tool(db, admin, "run_automation", {"automation": other, "key": item.key})
