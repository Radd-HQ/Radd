"""SLQ membership fields (RADD-1497): `reporter_team` / `assignee_team` (teams) and
`reporter_group` / `assignee_group` (groups), plus the widened plugin-field seam:
IN / NOT IN, autocomplete names and values, and the read-restriction link.

DB-backed; flushed, never committed — the session rolls back at teardown.
"""

import uuid

import pytest

from radd.kernel import registries
from radd.modules.groups import service as groups
from radd.modules.items import service as items_service
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.items.service.visibility import plugin_fields_revealing
from radd.modules.items.slq import compile_query, parse
from radd.modules.items.slq.errors import SlqError
from radd.modules.items.slq.suggest import _field_candidates, _operator_candidates
from radd.modules.items.slq.suggest_values import SuggestScope, value_candidates
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams import service as teams
from radd.modules.teams.schemas import TeamCreate
from sqlalchemy import select

from _factories import make_user


async def _run(db, query: str, actor) -> set[uuid.UUID]:
    compiled = await compile_query(
        db, parse(query), definitions_by_key={}, current_user_id=actor.id
    )
    stmt = select(WorkItem.id)
    if compiled.where is not None:
        stmt = stmt.where(compiled.where)
    return set((await db.execute(stmt)).scalars().all())


@pytest.fixture
async def world(db, admin):
    """A team with a direct member, a nested pair of directory groups, and one
    issue reported by (and one assigned to) each of three people: the team
    member, the nested-group member, and a local-only account in nothing."""
    stamp = uuid.uuid4().hex[:6]
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"MB{stamp[:4].upper()}", name="Membership")
    )
    teammate = await make_user(db, name="Teammate")
    nested = await make_user(db, name="Nested member")
    loner = await make_user(db, name="Local only")

    team = await teams.create_team(db, TeamCreate(name=f"Lighting {stamp}"), admin.id)
    await teams.add_team_member(db, team.id, teammate.id, admin.id)

    parent = await groups.upsert_group(
        db, dn=f"cn=pipeline-global-{stamp},ou=groups,dc=x", name=f"pipeline-global-{stamp}"
    )
    child = await groups.upsert_group(
        db, dn=f"cn=pipeline-lighting-{stamp},ou=groups,dc=x", name=f"pipeline-lighting-{stamp}"
    )
    await groups.set_parents(db, child, [parent.id])
    await groups.replace_members(db, child, [nested.id])

    reported, assigned = {}, {}
    for who, person in (("teammate", teammate), ("nested", nested), ("loner", loner)):
        reported[who] = await items_service.create_item(
            db, ItemCreate(project_id=project.id, title=f"by {who}", reporter_id=person.id), admin
        )
        assigned[who] = await items_service.create_item(
            db, ItemCreate(project_id=project.id, title=f"for {who}", assignee_id=person.id), admin
        )
    return {
        "project": project,
        "team": team,
        "parent": parent,
        "child": child,
        "reported": reported,
        "assigned": assigned,
        "people": {"teammate": teammate, "nested": nested, "loner": loner},
    }


async def test_reporter_and_assignee_team(db, admin, world):
    team = world["team"].name
    ids = await _run(db, f'reporter_team = "{team}"', admin)
    assert ids == {world["reported"]["teammate"].id}
    ids = await _run(db, f'assignee_team = "{team}"', admin)
    assert ids == {world["assigned"]["teammate"].id}
    # `!=` is the complement: the other reporters, and every item with no reporter at all.
    ids = await _run(db, f'reporter_team != "{team}"', admin)
    assert world["reported"]["nested"].id in ids and world["reported"]["loner"].id in ids
    assert world["reported"]["teammate"].id not in ids
    # `~` reaches by substring.
    ids = await _run(db, 'reporter_team ~ "lighting"', admin)
    assert ids == {world["reported"]["teammate"].id}


async def test_reporter_group_by_name_dn_and_nesting(db, admin, world):
    parent, child = world["parent"], world["child"]
    # Membership is nested: a member of the child group is in the parent.
    for value in (parent.name, parent.dn, child.name, child.dn):
        ids = await _run(db, f'reporter_group = "{value}"', admin)
        assert ids == {world["reported"]["nested"].id}, value
    ids = await _run(db, f'assignee_group = "{parent.name}"', admin)
    assert ids == {world["assigned"]["nested"].id}
    # A local-only account is in no group: it matches nothing, and the
    # complement holds it.
    ids = await _run(db, f'reporter_group != "{parent.name}"', admin)
    assert world["reported"]["loner"].id in ids and world["reported"]["nested"].id not in ids


async def test_plugin_fields_take_in_and_not_in(db, admin, world):
    team = world["team"].name
    ids = await _run(db, f'reporter_team IN ("{team}", "No such team")', admin)
    assert ids == {world["reported"]["teammate"].id}
    ids = await _run(db, f'reporter_team NOT IN ("{team}")', admin)
    assert world["reported"]["teammate"].id not in ids and world["reported"]["loner"].id in ids
    # The precedent plugin field gains the operator too.
    assert await _run(db, "logged_by IN (nobody@example.com)", admin) == set()
    with pytest.raises(SlqError):
        await _run(db, "reporter_team IS EMPTY", admin)


async def test_me_means_nothing_for_a_membership_field(db, admin, world):
    assert await _run(db, "reporter_team = me", admin) == set()
    assert await _run(db, "reporter_group = me", admin) == set()


async def test_autocomplete_knows_the_fields_and_their_values(db, admin, world):
    names = {c.value for c in _field_candidates({}, sortable_only=False)}
    assert {
        "reporter_team",
        "assignee_team",
        "reporter_group",
        "assignee_group",
        "logged_by",
    } <= names
    assert "reporter_team" not in {c.value for c in _field_candidates({}, sortable_only=True)}
    ops = {c.value for c in _operator_candidates("reporter_group", {})}
    assert {"=", "!=", "~", "IN", "NOT IN"} <= ops and "IS EMPTY" not in ops
    stamp = world["team"].name.split()[-1]
    values = {
        c.value for c in await value_candidates(db, SuggestScope(), "reporter_team", stamp, {})
    }
    assert world["team"].name in values
    values = {
        c.value
        for c in await value_candidates(
            db, SuggestScope(), "reporter_group", f"pipeline-global-{stamp}", {}
        )
    }
    assert world["parent"].name in values
    assert (
        await value_candidates(db, SuggestScope(), "logged_by", "", {}) == []
    )  # no source declared


def test_a_restricted_reporter_denies_the_fields_that_reveal_it():
    assert plugin_fields_revealing(set()) == set()
    assert plugin_fields_revealing({"reporter"}) == {"reporter_team", "reporter_group"}
    assert plugin_fields_revealing({"assignee"}) == {"assignee_team", "assignee_group"}
    assert registries.slq_fields["reporter_group"].reveals == ("reporter",)
