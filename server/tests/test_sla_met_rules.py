"""RADD-1299 — SLA targets say what "met" means; a policy can filter on the
reporter's team.

The modes are pure (`metrules`) and tested bare; the DB tests drive real
transitions and comments through `evaluate_items`, the function every SLA
surface reads, and pin that an unconfigured policy behaves exactly as before.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.comments import service as comments
from radd.modules.comments.schemas import CommentCreate
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.slas import evaluation, metrules, service as slas
from radd.modules.slas.schemas import PolicyCreate
from radd.modules.slas.types import SlaKind, SlaMetOn
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate
from radd.modules.workflow import service as workflow

T0 = datetime(2026, 9, 1, 9, 0)
TRIAGE, BACKLOG, CANCELED = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _stays(*states):
    return [metrules.Stay(state, T0 + timedelta(hours=i)) for i, state in enumerate(states)]


def test_leaving_counts_any_move_out_and_a_start_elsewhere():
    chosen = frozenset({str(TRIAGE)})
    assert metrules.state_met_at(SlaMetOn.LEAVES_STATES, chosen, _stays(TRIAGE, CANCELED)) == T0 + timedelta(hours=1)
    assert metrules.state_met_at(SlaMetOn.LEAVES_STATES, chosen, _stays(BACKLOG)) == T0  # never waited
    assert metrules.state_met_at(SlaMetOn.LEAVES_STATES, chosen, _stays(TRIAGE)) is None  # still there


def test_entering_is_the_first_arrival_and_bouncing_back_does_not_reopen():
    chosen = frozenset({str(BACKLOG)})
    assert metrules.state_met_at(SlaMetOn.ENTERS_STATES, chosen, _stays(TRIAGE, BACKLOG, TRIAGE)) == T0 + timedelta(hours=1)
    assert metrules.state_met_at(SlaMetOn.ENTERS_STATES, chosen, _stays(TRIAGE, CANCELED)) is None


def test_replies_never_count_the_reporter_or_automation():
    reporter, outsider, agent = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    replies = [(reporter, T0), (SYSTEM_ACTOR_ID, T0 + timedelta(minutes=1)),
               (outsider, T0 + timedelta(minutes=2)), (agent, T0 + timedelta(minutes=3))]
    assert metrules.reply_met_at(replies, reporter, None) == T0 + timedelta(minutes=2)
    assert metrules.reply_met_at(replies, reporter, frozenset({agent})) == T0 + timedelta(minutes=3)
    assert metrules.reply_met_at(replies, reporter, frozenset()) is None


# --- against the database -------------------------------------------------


@pytest.fixture
async def world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        people = {}
        for name in ("reporter", "agent", "outsider"):
            people[name] = User(email=f"slm-{name}-{uuid.uuid4().hex[:6]}@example.com", name=name,
                                instance_role=InstanceRole.ADMIN.value)
        db.add_all(people.values())
        await db.flush()
        project = await projects_service.create_project(db, ProjectCreate(key="SLM", name="SLA met rules"))
        states = {state.name: state for state in await workflow.list_states(db, project.id)}
        desk = await teams_service.create_team(db, TeamCreate(name=f"Desk {uuid.uuid4().hex[:4]}"))
        await teams_service.add_team_member(db, desk.id, people["agent"].id)
        yield db, people, project, states, desk
        await db.rollback()
    await engine.dispose()


async def _create(db, data):
    return await slas.create_policy(db, data, SYSTEM_ACTOR_ID)


async def _item(db, project, reporter, **extra):
    read = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t", **extra), reporter)
    return (await items_service.items_by_ids(db, [read.id]))[read.id]


async def _met(db, policy, item, kind):
    result = await evaluation.evaluate_items(db, policy, [item.id])
    return result[item.id][kind][1].met_at


async def test_an_unconfigured_policy_keeps_todays_rules(world):
    db, people, project, _states, _desk = world
    policy = await _create(db, PolicyCreate(project_id=project.id, name="Plain",
                                                       response_minutes=60, resolution_minutes=600))
    assert (policy.response_met_on, policy.resolution_met_on) == (SlaMetOn.FIRST_REPLY, SlaMetOn.DONE)
    item = await _item(db, project, people["reporter"])
    await comments.create_comment(db, item.id, CommentCreate(body="on it"), people["outsider"])
    assert await _met(db, policy, item, SlaKind.RESPONSE) is not None


async def test_triage_response_is_met_by_leaving_triage(world):
    db, people, project, states, _desk = world
    first = next(iter(sorted(states.values(), key=lambda s: s.position)))
    other = next(s for s in states.values() if s.id != first.id)
    policy = await _create(db, PolicyCreate(
        project_id=project.id, name="Triage", response_minutes=240,
        response_met_on=SlaMetOn.LEAVES_STATES, response_state_ids=[first.id]))
    item = await _item(db, project, people["reporter"], state_id=first.id)
    assert await _met(db, policy, item, SlaKind.RESPONSE) is None  # still in the first state
    await comments.create_comment(db, item.id, CommentCreate(body="a reply is not triage"), people["agent"])
    assert await _met(db, policy, item, SlaKind.RESPONSE) is None
    await items_service.update_item(db, item.id, ItemUpdate(state_id=other.id), people["agent"])
    assert await _met(db, policy, item, SlaKind.RESPONSE) is not None


async def test_team_replies_and_the_assigned_team_fallback(world):
    db, people, project, _states, desk = world
    by_desk = await _create(db, PolicyCreate(
        project_id=project.id, name="Desk replies", response_minutes=60,
        response_met_on=SlaMetOn.REPLY_BY_TEAMS, response_team_ids=[desk.id]))
    item = await _item(db, project, people["reporter"])
    await comments.create_comment(db, item.id, CommentCreate(body="not the desk"), people["outsider"])
    assert await _met(db, by_desk, item, SlaKind.RESPONSE) is None
    await comments.create_comment(db, item.id, CommentCreate(body="the desk"), people["agent"])
    assert await _met(db, by_desk, item, SlaKind.RESPONSE) is not None

    assigned = await _create(db, PolicyCreate(
        project_id=project.id, name="Owning team", response_minutes=60,
        response_met_on=SlaMetOn.REPLY_BY_ASSIGNED_TEAM))
    owned = await _item(db, project, people["reporter"], team_id=desk.id)
    unowned = await _item(db, project, people["reporter"])
    for target in (owned, unowned):
        await comments.create_comment(db, target.id, CommentCreate(body="outsider"), people["outsider"])
    assert await _met(db, assigned, owned, SlaKind.RESPONSE) is None  # the owning team has not replied
    assert await _met(db, assigned, unowned, SlaKind.RESPONSE) is not None  # no team: anyone counts


async def test_reporter_team_filter_decides_the_match(world):
    db, people, project, _states, desk = world
    await _create(db, PolicyCreate(project_id=project.id, name="Desk-reported",
                                              response_minutes=30, reporter_team_ids=[desk.id], position=0))
    fallback = await _create(db, PolicyCreate(project_id=project.id, name="Everyone",
                                                         response_minutes=240, position=1))
    from_desk = await _item(db, project, people["agent"])
    from_outside = await _item(db, project, people["outsider"])
    assert (await slas.matched_policy(db, from_desk)).name == "Desk-reported"
    assert (await slas.matched_policy(db, from_outside)).id == fallback.id


async def test_half_configured_rules_are_refused(world):
    db, _people, project, _states, _desk = world
    with pytest.raises(ConflictError):
        await _create(db, PolicyCreate(project_id=project.id, name="No states", response_minutes=5,
                                                  response_met_on=SlaMetOn.ENTERS_STATES))
    with pytest.raises(ConflictError):
        await _create(db, PolicyCreate(project_id=project.id, name="Foreign state", response_minutes=5,
                                                  response_met_on=SlaMetOn.ENTERS_STATES,
                                                  response_state_ids=[uuid.uuid4()]))
    with pytest.raises(ConflictError):
        await _create(db, PolicyCreate(project_id=project.id, name="No teams", response_minutes=5,
                                                  response_met_on=SlaMetOn.REPLY_BY_TEAMS))
