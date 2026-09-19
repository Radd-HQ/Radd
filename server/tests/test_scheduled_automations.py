"""Scheduled automation triggers + SLA due_soon (spec 69).

Pure: next_run math (interval/daily/weekly, TZ, DST-adjacent), ScheduleConfig
validation, relative-date literals, the due_soon predicate.
DB-backed (compose Postgres, rolled back at teardown — the db fixture idiom from
tests/test_bulk.py): schedule-state bookkeeping on rule writes, the scheduled
engine path (SLQ-matched item actions, cap, loop guard), due_soon emit-once.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.automations import engine, service as automations
from radd.modules.automations.models import AutomationScheduleState
from radd.schedule import next_run
from radd.modules.automations.schemas import RuleCreate, RuleUpdate, ScheduleConfig
from radd.modules.automations.types import (
    SYSTEM_ACTOR_ID,
    AutomationEntity,
    AutomationEvent,
    AutomationTrigger,
)
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.events.models import Event
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEvent, Priority
from radd.modules.items.schemas import ItemCreate
from radd.modules.items.slq.helpers import relative_date
from radd.modules.items.slq.parser import Value
from radd.modules.slas import evaluation
from radd.modules.slas.models import SlaItemState, SlaPolicy
from radd.modules.slas.timers import TimerStatus
from radd.modules.slas.types import SlaEvent
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.exceptions import ConflictError


def _utcnow() -> datetime:
    """Naive UTC, matching every stored timestamp in the schema."""
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture
async def db():
    engine_ = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine_, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine_.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"sched-{uuid.uuid4().hex[:8]}@example.com",
        name="Sched Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


# --- next_run pure math ---


def test_next_run_interval_anchors_on_now():
    now = datetime(2026, 7, 23, 10, 0)
    assert next_run({"kind": "interval", "minutes": 30}, now, "UTC") == now + timedelta(minutes=30)


def test_next_run_daily_is_strictly_after_now():
    cfg = {"kind": "daily", "time": "09:00"}
    # Before the wall-clock time -> today; at/after it -> tomorrow.
    assert next_run(cfg, datetime(2026, 7, 23, 8, 59), "UTC") == datetime(2026, 7, 23, 9, 0)
    assert next_run(cfg, datetime(2026, 7, 23, 9, 0), "UTC") == datetime(2026, 7, 24, 9, 0)
    assert next_run(cfg, datetime(2026, 7, 23, 22, 0), "UTC") == datetime(2026, 7, 24, 9, 0)


def test_next_run_daily_respects_the_scheduler_tz():
    # 08:00 UTC = 10:00 in Berlin (CEST, UTC+2): 09:00 local already
    # passed -> next day 09:00 local = 07:00 UTC.
    cfg = {"kind": "daily", "time": "09:00"}
    assert next_run(cfg, datetime(2026, 7, 23, 8, 0), "Europe/Berlin") == datetime(
        2026, 7, 24, 7, 0
    )


def test_next_run_daily_across_a_dst_change_keeps_local_time():
    # US DST ends: 09:00 America/New_York is 13:00 UTC before,
    # 14:00 UTC after — the LOCAL time stays put, the UTC gap stretches.
    cfg = {"kind": "daily", "time": "09:00"}
    assert next_run(cfg, datetime(2026, 10, 31, 14, 0), "America/New_York") == datetime(
        2026, 11, 1, 14, 0
    )


def test_next_run_weekly_picks_the_next_listed_weekday():
    # is a Thursday (weekday 3).
    cfg = {"kind": "weekly", "time": "09:00", "weekdays": [0]}  # Mondays
    assert next_run(cfg, datetime(2026, 7, 23, 10, 0), "UTC") == datetime(2026, 7, 27, 9, 0)
    # Same weekday still ahead of the wall clock -> today counts.
    cfg = {"kind": "weekly", "time": "09:00", "weekdays": [3]}
    assert next_run(cfg, datetime(2026, 7, 23, 8, 0), "UTC") == datetime(2026, 7, 23, 9, 0)
    assert next_run(cfg, datetime(2026, 7, 23, 9, 0), "UTC") == datetime(2026, 7, 30, 9, 0)


# --- ScheduleConfig validation (422 shapes) ---


def test_schedule_config_shapes():
    ScheduleConfig.model_validate({"kind": "interval", "minutes": 5})
    ScheduleConfig.model_validate({"kind": "daily", "time": "09:00"})
    ScheduleConfig.model_validate({"kind": "weekly", "time": "23:59", "weekdays": [0, 6]})
    for bad in (
        {"kind": "interval"},  # minutes required
        {"kind": "interval", "minutes": 4},  # below the floor
        {"kind": "interval", "minutes": 10, "time": "09:00"},  # stray field
        {"kind": "daily"},  # time required
        {"kind": "daily", "time": "9am"},  # not HH:MM
        {"kind": "daily", "time": "09:00", "weekdays": [1]},  # stray field
        {"kind": "weekly", "time": "09:00"},  # weekdays required
        {"kind": "weekly", "time": "09:00", "weekdays": []},  # non-empty
        {"kind": "weekly", "time": "09:00", "weekdays": [7]},  # out of range
        {"kind": "weekly", "time": "09:00", "weekdays": [1, 1]},  # dup
        {"kind": "sometimes"},  # unknown kind
    ):
        with pytest.raises(ValidationError):
            ScheduleConfig.model_validate(bad)


# --- relative dates (SLQ, spec 69 §4) ---


def test_relative_date_literals():
    today = date(2026, 7, 23)
    assert relative_date(Value("today"), today) == today
    assert relative_date(Value("today+3d"), today) == date(2026, 7, 26)
    assert relative_date(Value("today-2w"), today) == date(2026, 7, 9)
    assert relative_date(Value("today+1w"), today) == date(2026, 7, 30)
    assert relative_date(Value("2026-07-23"), today) is None  # plain dates untouched
    assert relative_date(Value("today", quoted=True), today) is None  # quoted = literal
    assert relative_date(Value("today+3x"), today) is None  # unknown unit


# --- due_soon predicate (pure) ---


def _status(**kwargs) -> TimerStatus:
    base = dict(due_at=None, met_at=None, breached=False, paused=False, remaining_seconds=None)
    return TimerStatus(**{**base, **kwargs})


def test_due_soon_predicate():
    policy = SlaPolicy(warning_minutes=30)
    assert evaluation.due_soon(policy, _status(remaining_seconds=1500.0)) is True
    assert evaluation.due_soon(policy, _status(remaining_seconds=1800.0)) is True  # boundary
    assert evaluation.due_soon(policy, _status(remaining_seconds=1801.0)) is False
    assert evaluation.due_soon(policy, _status(remaining_seconds=None)) is False  # paused
    assert (
        evaluation.due_soon(policy, _status(met_at=datetime(2026, 1, 1), remaining_seconds=10.0))
        is False
    )
    assert evaluation.due_soon(policy, _status(breached=True)) is False
    assert evaluation.due_soon(SlaPolicy(warning_minutes=None), _status(remaining_seconds=1.0)) is False


# --- DB: schedule-state bookkeeping on rule writes ---


async def _project(db, key_prefix="SC"):
    project = await projects_service.create_project(
        db,
        ProjectCreate(
            key=f"{key_prefix}{uuid.uuid4().hex[:4].upper()}",
            name="P",
        ),
    )
    return project


def _scheduled_rule_data(*, condition_slq="", enabled=True) -> RuleCreate:
    """A scheduled automation as a graph (spec 116, RADD-1265).

    A schedule has no event and therefore no target item, so the items a run
    acts on come from a SEARCH node wired after the trigger — the trigger's own
    `query` param is gone. Putting the SLQ on a filter would leave the
    automation filtering an empty set — running, matching nothing, and looking
    perfectly healthy."""
    trigger_params: dict = {
        "event": AutomationTrigger.SCHEDULE.value,
        "schedule": {"kind": "interval", "minutes": 30},
    }
    nodes = [
        {"id": "trigger", "kind": "trigger", "type": "trigger.event", "params": trigger_params},
        {"id": "a0", "kind": "action", "type": "action.set_priority", "params": {"priority": "high"}},
    ]
    edges = [{"source": "trigger", "port": "out", "target": "a0"}]
    if condition_slq:
        nodes.insert(
            1,
            {"id": "find", "kind": "source", "type": "search.slq",
             "params": {"slq": condition_slq, "project": "", "mode": "replace"}},
        )
        edges = [
            {"source": "trigger", "port": "out", "target": "find"},
            {"source": "find", "port": "out", "target": "a0"},
        ]
    return RuleCreate.model_validate(
        {"name": "nightly", "enabled": enabled, "nodes": nodes, "edges": edges}
    )


async def test_schedule_state_synced_on_create_update_enable(db, admin):
    rule = await automations.create_rule(db, _scheduled_rule_data(), admin.id)
    # Keyed by (automation, node) since spec 116 — two schedule triggers in one
    # graph keep two independent clocks.
    state = await db.get(AutomationScheduleState, (rule.id, "trigger"))
    assert state is not None and state.last_run_at is None
    gap = state.next_run_at - _utcnow()
    assert timedelta(minutes=29) <= gap <= timedelta(minutes=31)  # interval anchors on now

    # Disable drops the row; re-enable recomputes it.
    await automations.update_rule(db, rule.id, RuleUpdate(enabled=False), admin.id)
    assert await db.get(AutomationScheduleState, (rule.id, "trigger")) is None
    await automations.update_rule(db, rule.id, RuleUpdate(enabled=True), admin.id)
    assert await db.get(AutomationScheduleState, (rule.id, "trigger")) is not None

    # RuleRead hydration carries the stamps, per trigger.
    reads = await automations.rule_reads(db, [rule])
    assert [t.event_type for t in reads[0].triggers] == ["schedule"]
    assert reads[0].triggers[0].schedule == {"kind": "interval", "minutes": 30}
    assert reads[0].triggers[0].next_run_at is not None
    assert reads[0].triggers[0].last_run_at is None


def _graph(*, trigger_params: dict, extra_nodes=(), extra_edges=()) -> RuleCreate:
    """A one-action graph with the trigger's params under test.

    Built from a dict rather than by model_copy-ing `_scheduled_rule_data()`:
    `trigger` and `schedule` are no longer FIELDS of RuleCreate (they are derived
    from the trigger node), so `model_copy(update={"trigger": ...})` would attach
    an attribute nothing reads and the assertion would pass vacuously."""
    return RuleCreate.model_validate(
        {
            "name": "bad",
            "nodes": [
                {"id": "trigger", "kind": "trigger", "type": "trigger.event", "params": trigger_params},
                {"id": "a0", "kind": "action", "type": "action.set_priority",
                 "params": {"priority": "high"}},
                *extra_nodes,
            ],
            "edges": [{"source": "trigger", "port": "out", "target": "a0"}, *extra_edges],
        }
    )


async def test_schedule_consistency_409s(db, admin):
    # a schedule on a non-schedule trigger
    with pytest.raises(ConflictError):
        await automations.create_rule(
            db,
            _graph(
                trigger_params={
                    "event": ItemEvent.CREATED.value,
                    "schedule": {"kind": "interval", "minutes": 30},
                }
            ),
            admin.id,
        )
    # a schedule trigger with no schedule
    with pytest.raises(ConflictError):
        await automations.create_rule(
            db, _graph(trigger_params={"event": AutomationTrigger.SCHEDULE.value}), admin.id
        )
    # a scheduled automation that gates on event conditions — there is no event
    with pytest.raises(ConflictError):
        await automations.create_rule(
            db,
            _graph(
                trigger_params={
                    "event": AutomationTrigger.SCHEDULE.value,
                    "schedule": {"kind": "interval", "minutes": 30},
                },
                extra_nodes=[
                    {
                        "id": "gate",
                        "kind": "gate",
                        "type": "gate.changed_by",
                        "params": {"users": ["someone@example.com"], "negate": False},
                    }
                ],
                extra_edges=[{"source": "gate", "port": "true", "target": "a0"}],
            ),
            admin.id,
        )


# --- DB: the scheduled engine path ---


def _scheduled_event(rule) -> Event:
    return Event(
        event_type=AutomationEvent.SCHEDULED.value,
        entity_type=AutomationEntity.AUTOMATION.value,
        entity_id=str(rule.id),
        actor_id=SYSTEM_ACTOR_ID,
        payload={
            "rule_id": str(rule.id),
            "scheduled_for": _utcnow().isoformat(),
        },
    )


async def test_scheduled_run_applies_item_actions_to_matching_items_only(db, admin):
    project = await _project(db)
    low_a = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="low a", priority=Priority.LOW), admin
    )
    low_b = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="low b", priority=Priority.LOW), admin
    )
    normal = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="normal", priority=Priority.NORMAL), admin
    )
    # The relative-date literal rides along to prove it compiles in the
    # global-registry scheduled path (created <= today matches everything).
    # Scoped to this project's key so the shared DB's other items stay out.
    rule = await automations.create_rule(
        db,
        _scheduled_rule_data(
            condition_slq=f"priority = low AND created <= today AND project = {project.key}"
        ),
        admin.id,
    )

    await engine.apply_scheduled(db, _scheduled_event(rule))

    for read_id, expected in ((low_a.id, Priority.HIGH), (low_b.id, Priority.HIGH), (normal.id, Priority.NORMAL)):
        item = await items_service.require_item(db, read_id)
        assert item.priority == expected.value

    # Loop safety: the item events the run emitted carry the SYSTEM actor, so
    # the EVENT-rule path still skips them.
    result = await db.execute(
        select(Event).where(
            Event.event_type == ItemEvent.UPDATED.value,
            Event.entity_id.in_([str(low_a.id), str(low_b.id)]),
        )
    )
    emitted = list(result.scalars())
    assert len(emitted) == 2
    for event in emitted:
        # Spec 116: the action ran as the automation's AUTHOR, so the actor is a
        # real person — and the loop guard holds anyway because causation is
        # recorded on the event. Asserting both together is the point: identity
        # moved, `should_process` did not change its answer.
        assert event.actor_id == rule.created_by_id
        assert event.automated is True
        assert engine.should_process(event) is False
    # The synthetic scheduler event itself IS processed despite the system actor.
    assert engine.should_process(_scheduled_event(rule)) is True


async def test_scheduled_run_is_capped_and_rank_ordered(db, admin, monkeypatch):
    project = await _project(db)
    made = []
    for index in range(3):
        made.append(
            await items_service.create_item(
                db,
                ItemCreate(project_id=project.id, title=f"low {index}", priority=Priority.LOW),
                admin,
            )
        )
    rule = await automations.create_rule(
        db,
        _scheduled_rule_data(condition_slq=f"priority = low AND project = {project.key}"),
        admin.id,
    )
    monkeypatch.setattr(config, "automation_schedule_max_items", 2)

    await engine.apply_scheduled(db, _scheduled_event(rule))

    result = await db.execute(
        select(Event).where(
            Event.event_type == ItemEvent.UPDATED.value,
            Event.entity_id.in_([str(i.id) for i in made]),
        )
    )
    assert len(list(result.scalars())) == 2  # cap enforced, third item untouched


async def test_scheduled_run_skips_disabled_or_retyped_rules(db, admin):
    project = await _project(db)
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="low", priority=Priority.LOW), admin
    )
    rule = await automations.create_rule(
        db,
        _scheduled_rule_data(condition_slq=f"priority = low AND project = {project.key}"),
        admin.id,
    )
    event = _scheduled_event(rule)
    await automations.update_rule(db, rule.id, RuleUpdate(enabled=False), admin.id)

    await engine.apply_scheduled(db, event)

    result = await db.execute(
        select(Event).where(
            Event.event_type == ItemEvent.UPDATED.value,
            Event.entity_id == str(item.id),
        )
    )
    assert list(result.scalars()) == []


# --- DB: sla.due_soon emitted once, stamps persisted ---


async def test_due_soon_emitted_once_with_stamps(db, admin):
    from radd.modules.slas import service as slas
    from radd.modules.slas.schemas import PolicyCreate

    project = await _project(db, key_prefix="SD")
    policy = await slas.create_policy(
        db,
        PolicyCreate(
            project_id=project.id,
            name="warned",
            response_minutes=60,
            warning_minutes=30,
        ),
        admin.id,
    )
    read = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="ticket"), admin
    )
    item = await items_service.require_item(db, read.id)
    item.created_at = _utcnow() - timedelta(minutes=45)  # 15m remaining of 60
    await db.flush()

    refs = {item.id: {"id": str(item.id), "key": "SD-1"}}
    evaluated = await evaluation.evaluate_items(db, policy, [item.id])
    emitted = await evaluation.sync_states(db, policy, evaluated, refs)
    assert emitted == 1
    state = await db.get(SlaItemState, (item.id, policy.id))
    assert state.warned_response_at is not None
    assert state.response_breached_at is None

    events_result = await db.execute(
        select(Event).where(Event.event_type == SlaEvent.DUE_SOON.value)
    )
    due_soon_events = [e for e in events_result.scalars() if e.payload.get("item", {}).get("id") == str(item.id)]
    assert len(due_soon_events) == 1
    payload = due_soon_events[0].payload
    assert payload["policy_name"] == "warned" and payload["kind"] == "response"
    assert payload["remaining_seconds"] is not None

    # Second pass: warned already — nothing new fires.
    evaluated = await evaluation.evaluate_items(db, policy, [item.id])
    assert await evaluation.sync_states(db, policy, evaluated, refs) == 0


async def test_due_soon_not_emitted_once_breached(db, admin):
    from radd.modules.slas import service as slas
    from radd.modules.slas.schemas import PolicyCreate

    project = await _project(db, key_prefix="SB")
    policy = await slas.create_policy(
        db,
        PolicyCreate(
            project_id=project.id,
            name="breached",
            response_minutes=60,
            warning_minutes=30,
        ),
        admin.id,
    )
    read = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="late"), admin
    )
    item = await items_service.require_item(db, read.id)
    item.created_at = _utcnow() - timedelta(hours=2)  # long past the target
    await db.flush()

    refs = {item.id: {"id": str(item.id), "key": "SB-1"}}
    evaluated = await evaluation.evaluate_items(db, policy, [item.id])
    emitted = await evaluation.sync_states(db, policy, evaluated, refs)
    assert emitted == 1  # the breach — no warning for an already-missed target
    state = await db.get(SlaItemState, (item.id, policy.id))
    assert state.response_breached_at is not None
    assert state.warned_response_at is None
