"""Round-robin team assignment — the `assign_round_robin` action (RADD-1044).

Triage distributes: the action hands each new ticket to the NEXT member of a
named team, walking members in a stable order (by user id, so the cursor stays
meaningful as membership changes), skipping inactive and away accounts, and
leaving the item unassigned when nobody is eligible.

These pin the parts that are easy to get subtly wrong:

* distribution is fair AND in a stable order, and the per-team cursor advances
  across calls in one transaction (the read-your-writes the executor relies on);
* an away member (leave on) and an inactive one are passed over — the cursor
  lands on the assignee, never on a skipped member;
* nobody eligible -> pick returns None (the planner skip-logs, leaves the item
  unassigned, and does NOT advance the cursor);
* leave being absent turns away-skipping OFF rather than crashing.

DB-backed because the whole point is real teams, memberships, leave rows and the
cursor table; the `db`/`admin` fixtures mirror test_automation_arity.py.
"""

import uuid
from datetime import date

import pytest

from radd.config import settings
from radd.modules.automations import round_robin
from radd.modules.automations.engine import _manual_facts, _plan
from radd.modules.automations.types import PlanKind


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine_ = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine_, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine_.dispose()


@pytest.fixture
async def admin(db):
    from radd.modules.auth.models import User
    from radd.modules.auth.types import InstanceRole

    user = User(
        email=f"rr-admin-{uuid.uuid4().hex[:8]}@example.com",
        name="RR Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _member(db, n: int):
    from radd.modules.auth.models import User

    user = User(email=f"rr-{uuid.uuid4().hex[:8]}@example.com", name=f"Member {n}")
    db.add(user)
    await db.flush()
    return user


async def _team_with_members(db, admin, count: int):
    """A team with `count` active direct members, returned SORTED BY ID — the
    order round-robin walks, so the expected rotation is just this list."""
    from radd.modules.teams import service as teams_service
    from radd.modules.teams.schemas import TeamCreate

    team = await teams_service.create_team(
        db, TeamCreate(name=f"RR Team {uuid.uuid4().hex[:6]}"), actor_id=admin.id
    )
    members = [await _member(db, n) for n in range(count)]
    for member in members:
        await teams_service.add_team_member(db, team.id, member.id, actor_id=admin.id)
    return team, sorted(members, key=lambda u: u.id)


async def _mark_away(db, admin, user, on: date | None = None):
    from radd.modules.leave import service as leave_service
    from radd.modules.leave.schemas import LeaveCreate

    day = on or date.today()
    await leave_service.create(
        db, admin, LeaveCreate(user_id=user.id, label="ooo", start_date=day, end_date=day)
    )
    await db.flush()


# --- distribution + the cursor ------------------------------------------------


async def test_round_robin_distributes_in_stable_id_order(db, admin):
    """Five tickets across three members: 2/2/1, and always the next member in id
    order, wrapping. Each pick+advance runs in its OWN SAVEPOINT, mirroring the
    executor's per-item `_one` loop exactly — so this proves the cursor advance
    from one item is visible to the next within the transaction (the scalar-select
    read + Core-upsert write is what makes that hold across savepoints)."""
    team, members = await _team_with_members(db, admin, 3)

    picks = []
    for _ in range(5):
        async with db.begin_nested():
            chosen = await round_robin.pick_next(db, team)
            assert chosen is not None
            await round_robin.advance_cursor(db, team.id, chosen)
        picks.append(chosen)

    ordered = [m.id for m in members]
    assert picks == [ordered[0], ordered[1], ordered[2], ordered[0], ordered[1]]
    # Fair: 2 + 2 + 1 over five, nobody skipped.
    assert {ordered[0]: 2, ordered[1]: 2, ordered[2]: 1} == {
        m: picks.count(m) for m in ordered
    }


async def test_the_cursor_is_shared_per_team_not_per_caller(db, admin):
    """Two rules over one team must keep ONE rotation. The cursor is keyed by
    team, so a second, independent sequence of picks resumes where the first left
    off rather than restarting on the first member."""
    team, members = await _team_with_members(db, admin, 3)
    ordered = [m.id for m in members]

    first = await round_robin.pick_next(db, team)
    await round_robin.advance_cursor(db, team.id, first)
    assert first == ordered[0]

    # A different "rule" assigning from the same team picks the NEXT member.
    second = await round_robin.pick_next(db, team)
    assert second == ordered[1]


# --- skipping the ineligible --------------------------------------------------


async def test_an_away_member_is_skipped(db, admin):
    """Leave on: the away member never receives a ticket, and the cursor lands on
    the assignee (the next eligible), never on the one passed over."""
    team, members = await _team_with_members(db, admin, 3)
    await _mark_away(db, admin, members[1])

    picks = []
    for _ in range(4):
        chosen = await round_robin.pick_next(db, team)
        await round_robin.advance_cursor(db, team.id, chosen)
        picks.append(chosen)

    assert members[1].id not in picks
    assert set(picks) == {members[0].id, members[2].id}


async def test_an_inactive_member_is_skipped(db, admin):
    team, members = await _team_with_members(db, admin, 3)
    members[1].active = False
    await db.flush()

    picks = []
    for _ in range(4):
        chosen = await round_robin.pick_next(db, team)
        await round_robin.advance_cursor(db, team.id, chosen)
        picks.append(chosen)

    assert members[1].id not in picks
    assert set(picks) == {members[0].id, members[2].id}


# --- nobody eligible ----------------------------------------------------------


async def test_no_eligible_member_returns_none_and_does_not_advance(db, admin):
    """Every member away: the pick is None (the planner skip-logs and leaves the
    item unassigned), and the cursor is untouched — there was nothing to advance
    past."""
    team, members = await _team_with_members(db, admin, 2)
    for member in members:
        await _mark_away(db, admin, member)

    assert await round_robin.pick_next(db, team) is None
    # No cursor row was written.
    from radd.modules.automations.models import TeamAssignmentCursor

    assert await db.get(TeamAssignmentCursor, team.id) is None


async def test_a_team_with_no_members_returns_none(db, admin):
    team, _ = await _team_with_members(db, admin, 0)
    assert await round_robin.pick_next(db, team) is None


# --- leave optional -----------------------------------------------------------


async def test_away_skipping_is_off_when_the_leave_module_is_absent(db, admin, monkeypatch):
    """The leave reach is deferred + feature-detected. With the module present an
    away member is excluded; with it unloaded, `_away_user_ids` is empty and the
    member stays eligible — degraded, not crashed."""
    team, members = await _team_with_members(db, admin, 3)
    await _mark_away(db, admin, members[1])

    assert await round_robin._away_user_ids(db) == {members[1].id}

    without_leave = tuple(m for m in settings.modules if m != round_robin.LEAVE_MODULE)
    monkeypatch.setattr(settings, "modules", without_leave)
    assert round_robin.leave_service() is None
    assert await round_robin._away_user_ids(db) == set()
    # And a pick still succeeds, now including the (no-longer-skipped) member.
    assert await round_robin.pick_next(db, team) is not None


# --- the planner wires it to an item update + a cursor advance ----------------


async def test_the_planner_assigns_the_next_member_and_carries_the_cursor(db, admin):
    team, members = await _team_with_members(db, admin, 3)
    action = {"type": "assign_round_robin", "params": {"team": team.name}}

    plan = await _plan(
        db, action, None, None, admin, facts=_manual_facts(), rule_name="test"
    )

    assert plan.kind is PlanKind.ITEM_UPDATE
    assert plan.item_update is not None
    assert plan.item_update.assignee_id == members[0].id  # first in id order
    assert plan.cursor_advance == (team.id, members[0].id)


async def test_the_planner_skips_an_unknown_team(db, admin):
    action = {"type": "assign_round_robin", "params": {"team": "No Such Team"}}
    plan = await _plan(
        db, action, None, None, admin, facts=_manual_facts(), rule_name="test"
    )
    assert plan.kind is PlanKind.SKIP
    assert plan.cursor_advance is None


async def test_the_planner_skips_when_no_member_is_eligible(db, admin):
    team, members = await _team_with_members(db, admin, 2)
    for member in members:
        await _mark_away(db, admin, member)
    action = {"type": "assign_round_robin", "params": {"team": team.name}}

    plan = await _plan(
        db, action, None, None, admin, facts=_manual_facts(), rule_name="test"
    )
    assert plan.kind is PlanKind.SKIP
    assert "no eligible member" in plan.detail
    assert plan.cursor_advance is None
