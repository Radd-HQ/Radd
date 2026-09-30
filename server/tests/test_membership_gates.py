"""The membership gates (RADD-1498): "Person is in team" (automations, core) and
"Person is in directory group" (contributed by groups). Each runs against a real
node context over a seeded event — the reporter, the assignee, the actor and an
email, direct and nested membership, the inverted form, and the packet shapes
that must answer false.
"""

import uuid
from dataclasses import replace

import pytest

from radd.config import settings
from radd.kernel import registries
from radd.kernel.loader import load_plugins
from radd.modules.automations import engine
from radd.modules.automations.executor import _NodeContext
from radd.modules.automations.graph import Node, Packet
from radd.modules.automations.types import TYPE_GATE_PERSON_IN_TEAM, AutomationNodeKind
from radd.modules.groups import service as groups
from radd.modules.groups.automation import GATE_KEY as GROUP_GATE
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams import service as teams
from radd.modules.teams.schemas import TeamCreate

from _factories import make_user


@pytest.fixture(scope="module", autouse=True)
def _plugins_loaded():
    load_plugins(settings.modules)


@pytest.fixture
async def world(db, admin):
    stamp = uuid.uuid4().hex[:6]
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"MG{stamp[:4].upper()}", name="Membership gates")
    )
    teammate = await make_user(db, name="Teammate")
    nested = await make_user(db, name="Nested member")
    loner = await make_user(db, name="Local only")
    team = await teams.create_team(db, TeamCreate(name=f"Lighting {stamp}"), admin.id)
    await teams.add_team_member(db, team.id, teammate.id, admin.id)
    await teams.add_team_member(db, team.id, admin.id, admin.id)  # the actor of every seeded event
    parent = await groups.upsert_group(
        db, dn=f"cn=pipeline-global-{stamp},ou=g,dc=x", name=f"pipeline-global-{stamp}"
    )
    child = await groups.upsert_group(
        db, dn=f"cn=pipeline-lighting-{stamp},ou=g,dc=x", name=f"pipeline-lighting-{stamp}"
    )
    await groups.set_parents(db, child, [parent.id])
    await groups.replace_members(db, child, [nested.id])
    by_teammate = await items_service.create_item(
        db,
        ItemCreate(
            project_id=project.id,
            title="by teammate",
            reporter_id=teammate.id,
            assignee_id=nested.id,
        ),
        admin,
    )
    by_nested = await items_service.create_item(
        db,
        ItemCreate(
            project_id=project.id, title="by nested", reporter_id=nested.id, assignee_id=loner.id
        ),
        admin,
    )
    by_loner = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="by loner", reporter_id=loner.id), admin
    )
    return {
        "team": team,
        "parent": parent,
        "child": child,
        "teammate": teammate,
        "nested": nested,
        "loner": loner,
        "by_teammate": by_teammate,
        "by_nested": by_nested,
        "by_loner": by_loner,
    }


async def _answer(db, admin, gate_type: str, params: dict, item_ids: tuple) -> str:
    # A seeded (manual-run) event carries no actor; a real one does — say who
    # caused it, as `_event_facts` would from the event row.
    facts = replace(await engine._seeded_facts(db, "item", item_ids[0]), actor_id=str(admin.id))
    ctx = _NodeContext(
        session=db,
        actor=admin,
        node=Node(id="g", kind=AutomationNodeKind.GATE, type=gate_type, params=params),
        packet=Packet.of(facts, item=item_ids),
    )
    return await registries.automation_nodes[gate_type].plan(ctx)


async def test_person_in_team(db, admin, world):
    team = world["team"].name

    def ask(params, *items):
        return _answer(db, admin, TYPE_GATE_PERSON_IN_TEAM, params, tuple(i.id for i in items))

    assert await ask({"person": "reporter", "teams": [team]}, world["by_teammate"]) == "true"
    assert await ask({"person": "reporter", "teams": [team]}, world["by_nested"]) == "false"
    assert (
        await ask({"person": "reporter", "teams": [team], "negate": True}, world["by_nested"])
        == "true"
    )
    assert await ask({"person": "assignee", "teams": [team]}, world["by_teammate"]) == "false"
    # The actor: the admin seeded every event and is on the team.
    assert await ask({"person": "actor", "teams": [team]}, world["by_loner"]) == "true"
    # An email names one person outright.
    assert (
        await ask({"person": world["teammate"].email, "teams": [team]}, world["by_loner"]) == "true"
    )
    # Nothing to match against, and a packet that speaks for several items, both answer false.
    assert await ask({"person": "reporter", "teams": []}, world["by_teammate"]) == "false"
    assert (
        await ask({"person": "reporter", "teams": ["No such team"]}, world["by_teammate"])
        == "false"
    )
    assert (
        await ask({"person": "reporter", "teams": [team]}, world["by_teammate"], world["by_nested"])
        == "false"
    )


async def test_person_in_directory_group(db, admin, world):
    parent, child = world["parent"], world["child"]

    def ask(params, *items):
        return _answer(db, admin, GROUP_GATE, params, tuple(i.id for i in items))

    # Nested: a member of the child is in the parent — by name, by DN, by id.
    for value in (parent.name, parent.dn, str(parent.id), child.name):
        assert await ask({"person": "reporter", "groups": [value]}, world["by_nested"]) == "true", (
            value
        )
    assert (
        await ask({"person": "assignee", "groups": [parent.name]}, world["by_teammate"]) == "true"
    )
    assert (
        await ask({"person": "reporter", "groups": [parent.name]}, world["by_teammate"]) == "false"
    )
    assert (
        await ask(
            {"person": "reporter", "groups": [parent.name], "negate": True}, world["by_teammate"]
        )
        == "true"
    )
    # A local-only account is in no group, so the plain form is false and the inverted form true.
    assert await ask({"person": "reporter", "groups": [parent.name]}, world["by_loner"]) == "false"
    assert (
        await ask(
            {"person": "reporter", "groups": [parent.name], "negate": True}, world["by_loner"]
        )
        == "true"
    )
    # The actor (admin) is in no directory group.
    assert await ask({"person": "actor", "groups": [parent.name]}, world["by_loner"]) == "false"


def test_both_gates_are_in_the_catalog_with_both_arities():
    for key in (TYPE_GATE_PERSON_IN_TEAM, GROUP_GATE):
        spec = registries.automation_nodes[key]
        assert spec.kind == AutomationNodeKind.GATE.value
        assert spec.ports == ("true", "false") and spec.arity_options == ("set", "item")
        assert spec.default_params["person"] == "reporter"
