"""The relation algebra + the where/holds contract (RADD-823).

Executes `docs/specs/115-relations-semantics.md`: the chain lattice, the
unqualified≡@any rule, the lattice-aware token-scope meet, the downward-closed
resolvers, and — the one this mechanism is most likely to break silently — the
CONTRACT that a relation's two forms select the same rows: `where` compiled
against the database and `holds` evaluated in Python must agree on a fixture,
or every list disagrees with every gate.

Rolled-back transactions on the compose DB for the contract half; the algebra
half is pure.
"""

import uuid
from itertools import product

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.kernel import registries
from radd.modules.auth import authz, roles as auth_roles
from radd.modules.auth.models import User
from radd.modules.auth.scopes import _lattice_intersect
from radd.modules.auth.types import (
    RELATION_ANY,
    RELATION_ORDER,
    Permission,
    qualify_permission,
    relation_contains,
    relation_meet,
    relations_held,
    split_permission,
)

# Side effect: workflow's project.created hook seeds default states.
from radd.modules import workflow as _workflow  # noqa: F401
from radd.modules.items import service as items
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate

# A relation outside the chain — incomparable with team/own by definition.
_EXOTIC = "reviewed"


# --- the algebra (pure) --------------------------------------------------------


def test_unqualified_means_any_and_qualify_roundtrips():
    for base in ("item.update", "page.write", "view.delete"):
        assert split_permission(base) == (base, RELATION_ANY)
        for relation in (*RELATION_ORDER, _EXOTIC):
            atom = qualify_permission(base, relation)
            assert split_permission(atom) == (base, relation)
        # @any is never written out — the canonical spelling is the bare atom.
        assert qualify_permission(base, RELATION_ANY) == base


def test_containment_is_the_chain_property():
    """For every pair on the chain: contains ⟺ position ≤. Reflexive always;
    `any` contains everything; an off-chain relation only contains itself."""
    for outer, inner in product(RELATION_ORDER, RELATION_ORDER):
        expected = RELATION_ORDER.index(outer) <= RELATION_ORDER.index(inner)
        assert relation_contains(outer, inner) is expected
    for relation in (*RELATION_ORDER, _EXOTIC):
        assert relation_contains(relation, relation)
        assert relation_contains(RELATION_ANY, relation)
    assert not relation_contains(_EXOTIC, "own")
    assert not relation_contains("team", _EXOTIC)


def test_meet_is_the_narrower_and_commutative():
    for a, b in product((*RELATION_ORDER, _EXOTIC), repeat=2):
        assert relation_meet(a, b) == relation_meet(b, a)  # commutative
    for a, b in product(RELATION_ORDER, RELATION_ORDER):
        # On the chain the meet is the lower (narrower) of the two.
        lower = max((a, b), key=RELATION_ORDER.index)
        assert relation_meet(a, b) == lower
    assert relation_meet(_EXOTIC, "team") is None  # incomparable -> nothing
    assert relation_meet(_EXOTIC, RELATION_ANY) == _EXOTIC  # any contains it


def test_relations_held_answers_per_base():
    perms = {"item.read", "item.update@team", "item.update@own", "page.write@own"}
    assert relations_held(perms, "item.read") == {RELATION_ANY}
    assert relations_held(perms, "item.update") == {"team", "own"}
    assert relations_held(perms, "page.write") == {"own"}
    assert relations_held(perms, "view.delete") == frozenset()


def test_token_scope_meet_matches_the_normative_table():
    """The spec-113 intersection, lattice-aware — the four rows of the table."""
    account_team = frozenset({"item.read@team"})
    assert _lattice_intersect(account_team, frozenset({Permission.ITEM_READ})) == {
        "item.read@team"
    }
    account_any = frozenset({Permission.ITEM_READ})
    assert _lattice_intersect(account_any, frozenset({"item.read@team"})) == {"item.read@team"}
    assert _lattice_intersect(account_team, frozenset({"item.read@own"})) == {"item.read@own"}
    assert _lattice_intersect(account_team, frozenset({f"item.read@{_EXOTIC}"})) == frozenset()
    # With no qualifiers anywhere the meet degenerates to plain set intersection.
    plain = frozenset({Permission.ITEM_READ, Permission.ITEM_UPDATE})
    allowed = frozenset({Permission.ITEM_READ, Permission.COMMENT_WRITE})
    assert _lattice_intersect(plain, allowed) == (plain & allowed)


def test_scope_axis_ignores_the_relation_qualifier():
    """The axes are orthogonal: WHERE an atom is checked never changes with the
    qualifier — permission_parts/scope lookups resolve the base."""
    from radd.modules.auth.types import permission_parts, permission_scope_of

    assert permission_scope_of("item.update@team") == permission_scope_of("item.update")
    assert permission_parts("item.update@team") == ("item", "update")


# --- the resolvers (registry-backed, pure over a fake actor) -------------------


def _actor(user_id=None, team_ids=()):
    from radd.kernel.specs import RelationActor

    return RelationActor(
        user_id=user_id or uuid.uuid4(), team_ids=frozenset(team_ids)
    )


def test_relation_filter_closes_downward_and_fails_closed():
    actor = _actor()
    # @any -> unconstrained for an UNRESTRICTED actor (spec 121: items carry a
    # row guard, so for everyone else @any now means "every non-restricted row
    # plus the restricted ones you are on" — asserted in test_item_visibility).
    from dataclasses import replace

    assert authz.relation_filter("item", frozenset({RELATION_ANY}), replace(actor, unrestricted=True)) is None
    guarded = authz.relation_filter("item", frozenset({RELATION_ANY}), actor)
    assert guarded is not None and "visibility" in str(guarded)
    # Nothing held / unregistered qualifier -> matches NOTHING (false()), never all.
    for held in (frozenset(), frozenset({_EXOTIC})):
        clause = authz.relation_filter("item", held, actor)
        assert clause is not None and str(clause) == "false"
    # @team covers @own (the chain is normative): both specs' clauses OR'd.
    clause = str(authz.relation_filter("item", frozenset({"team"}), actor))
    assert "reporter_id" in clause  # own's column rides along
    own_only = str(authz.relation_filter("item", frozenset({"own"}), actor))
    assert "reporter_id" in own_only and "team_id" not in own_only


def test_relation_holds_row_agrees_with_the_chain():
    me = uuid.uuid4()
    team = uuid.uuid4()
    actor = _actor(user_id=me, team_ids=(team,))

    class Row:
        def __init__(self, reporter_id, team_id, visibility="public"):
            self.reporter_id = reporter_id
            self.team_id = team_id
            self.visibility = visibility  # spec 121: the item row guard reads it
            self.assignee_id = None

    mine = Row(me, None)
    teams_row = Row(uuid.uuid4(), team)
    other = Row(uuid.uuid4(), uuid.uuid4())
    holds = authz.relation_holds_row
    assert holds("item", frozenset({"own"}), actor, mine)
    assert not holds("item", frozenset({"own"}), actor, teams_row)
    assert holds("item", frozenset({"team"}), actor, teams_row)
    assert holds("item", frozenset({"team"}), actor, mine)  # downward closure
    assert not holds("item", frozenset({"team"}), actor, other)
    assert holds("item", frozenset({RELATION_ANY}), actor, other)


# --- the where/holds CONTRACT (DB) --------------------------------------------


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def test_registered_item_relations_where_and_holds_agree(db):
    """THE contract: for every registered item relation, the SQL form and the
    predicate form select the same rows on a fixture that exercises mine /
    my-team's / someone-else's. A pair that disagrees is a silent leak."""
    me = User(email=f"rs-{uuid.uuid4().hex[:8]}@example.com", name="Me", instance_role="admin")
    other = User(
        email=f"rs-{uuid.uuid4().hex[:8]}@example.com", name="Other", instance_role="admin"
    )
    db.add_all([me, other])
    await db.flush()
    await auth_roles.ensure_builtin_roles(db)
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"RS{uuid.uuid4().hex[:4].upper()}", name="R")
    )
    my_team = await teams_service.create_team(db, TeamCreate(name=f"RS {uuid.uuid4().hex[:6]}"))
    fixture_ids = set()
    for title, reporter, team_id in (
        ("mine", me, None),
        ("my team's", other, my_team.id),
        ("mine and my team's", me, my_team.id),
        ("someone else's", other, None),
    ):
        read = await items.create_item(
            db,
            ItemCreate(project_id=project.id, title=title, team_id=team_id),
            reporter,
        )
        fixture_ids.add(read.id)

    actor = await authz.relation_actor(db, me)
    rows = {
        item.id: item
        for item in (
            await db.execute(select(WorkItem).where(WorkItem.id.in_(fixture_ids)))
        ).scalars()
    }
    specs = registries.relations_for("item")
    assert set(specs) >= {"own", "team"}
    for key, spec in specs.items():
        via_where = set(
            (
                await db.execute(
                    select(WorkItem.id).where(WorkItem.id.in_(fixture_ids), spec.where(actor))
                )
            ).scalars()
        )
        if spec.holds is None:
            # Query-gated relation (RADD-844): the async gate IS the where-form,
            # so the contract is that the gate agrees with the filter per row.
            assert spec.expensive, f"relation '{key}': holds=None must be expensive"
            via_gate = {
                item_id
                for item_id, row in rows.items()
                if await authz.relation_holds_row_async(
                    db, "item", frozenset({key}), actor, row
                )
            }
            assert via_where == via_gate, f"relation '{key}': where/async-gate disagree"
            # The SYNC resolver must fail CLOSED on it — never wide.
            assert not any(
                authz.relation_holds_row("item", frozenset({key}), actor, row)
                for row in rows.values()
            )
            continue
        via_holds = {item_id for item_id, row in rows.items() if spec.holds(actor, row)}
        assert via_where == via_holds, f"relation '{key}': where/holds disagree"
