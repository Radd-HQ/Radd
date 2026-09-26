"""Holidays pause the SLA clock through the kernel socket (RADD-1031): the pure
math (a holiday pauses a whole day, like a weekend); a holiday recorded in `leave`
moves an open timer's deadline; one person's leave does NOT (an item's timer has
no person to be absent); and slas behaves the same with the provider gone.
"""

import uuid
from datetime import date, datetime, timedelta


from radd.kernel.registry import registries
from radd.kernel.sockets import Socket
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.leave import service as leave
from radd.modules.leave.schemas import LeaveCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.slas import calendar, evaluation, service as slas
from radd.modules.slas.schemas import PolicyCreate
from radd.modules.slas.timers import deadline, non_working_pauses
from radd.modules.slas.types import SlaKind
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate

MON_FRI = frozenset(range(5))
# A Wednesday, matching tests/test_sla.py's anchor.
FILED = datetime(2026, 7, 1, 10, 0)
THURSDAY = date(2026, 7, 2)
ONE_DAY_MINUTES = 24 * 60


# --- the pure math (no database, no socket) ---


def test_a_holiday_is_a_whole_day_pause():
    pauses = non_working_pauses(FILED, FILED + timedelta(days=3), MON_FRI, {THURSDAY})
    assert (datetime(2026, 7, 2), datetime(2026, 7, 3)) in pauses
    # …and the weekend it already produced is still there.
    assert (datetime(2026, 7, 4), datetime(2026, 7, 5)) in pauses


def test_a_holiday_pushes_the_deadline_a_full_day():
    """24h of active time from Wednesday 10:00 is due Thursday 10:00 — unless
    Thursday is a holiday, when the last 10 hours burn on Friday."""
    horizon = FILED + timedelta(days=20)
    plain = non_working_pauses(FILED, horizon, MON_FRI)
    assert deadline(FILED, ONE_DAY_MINUTES * 60, plain) == datetime(2026, 7, 2, 10, 0)
    with_holiday = non_working_pauses(FILED, horizon, MON_FRI, {THURSDAY})
    assert deadline(FILED, ONE_DAY_MINUTES * 60, with_holiday) == datetime(
        2026, 7, 3, 10, 0
    )


def test_slas_never_learns_leave_exists():
    """The socket is the seam, so the dependency must not exist in either
    direction — a direct call would work and would also make the SLA engine
    unloadable without the optional plugin."""
    from radd.modules.slas import plugin as slas_plugin

    declared = set(slas_plugin.depends_on) | set(slas_plugin.weak_depends)
    assert "leave" not in declared


# --- live: the socket, the provider, and the clock ---


async def _filed_item(db, admin, project_id):
    """An item whose creation is pinned to FILED. Assigned on the loaded instance, not
    by UPDATE + expire: the evaluator re-reads through the same identity map, and an
    expired attribute would lazy-load in a sync context (MissingGreenlet)."""
    read = await items_service.create_item(
        db, ItemCreate(project_id=project_id, title="Printer on fire"), admin
    )
    item = (await items_service.items_by_ids(db, [read.id]))[read.id]
    item.created_at = FILED
    await db.flush()
    return read.id


async def _day_policy(db, admin, project_id):
    """One working DAY of active time, work-week only — the resolution a studio
    shutdown is supposed to interrupt."""
    return await slas.create_policy(
        db,
        PolicyCreate(
            project_id=project_id,
            name="One working day",
            response_minutes=ONE_DAY_MINUTES,
            work_week_only=True,
        ),
        actor_id=admin.id,
    )


async def _holiday(db, admin, start: date, end: date) -> None:
    team = await teams_service.create_team(
        db, TeamCreate(name=f"Studio {uuid.uuid4().hex[:6]}"), actor_id=admin.id
    )
    await leave.create(
        db,
        admin,
        LeaveCreate(team_id=team.id, label="Studio shutdown", start_date=start, end_date=end),
    )


async def _due(db, policy, item_id):
    evaluated = await evaluation.evaluate_items(
        db, policy, [item_id], now=FILED + timedelta(minutes=5)
    )
    return evaluated[item_id][SlaKind.RESPONSE][1].due_at


async def test_a_holiday_moves_an_open_timers_deadline(db, admin):
    project = await projects_service.create_project(db, ProjectCreate(key="SLH", name="SLA Hol"))
    policy = await _day_policy(db, admin, project.id)
    item_id = await _filed_item(db, admin, project.id)

    assert await _due(db, policy, item_id) == datetime(2026, 7, 2, 10, 0)
    # The shutdown is declared AFTER the ticket was filed — the retro-change
    # rule: holidays are read at evaluation time, so an open timer moves.
    await _holiday(db, admin, THURSDAY, THURSDAY)
    assert await _due(db, policy, item_id) == datetime(2026, 7, 3, 10, 0)


async def test_a_two_day_shutdown_accrues_nothing(db, admin):
    project = await projects_service.create_project(db, ProjectCreate(key="SL2", name="SLA Hol 2"))
    policy = await _day_policy(db, admin, project.id)
    item_id = await _filed_item(db, admin, project.id)
    await _holiday(db, admin, THURSDAY, THURSDAY + timedelta(days=1))  # Thu + Fri

    # Thursday and Friday are gone, and the weekend after them was already gone,
    # so the last 10 hours land on Monday.
    assert await _due(db, policy, item_id) == datetime(2026, 7, 6, 10, 0)


async def test_personal_leave_does_not_pause_anything(db, admin):
    """A timer belongs to an item, not to a person: one engineer's holiday
    cannot be the reason a customer's ticket stops ageing."""
    project = await projects_service.create_project(db, ProjectCreate(key="SLP", name="SLA Pers"))
    policy = await _day_policy(db, admin, project.id)
    item_id = await _filed_item(db, admin, project.id)
    await leave.create(
        db,
        admin,
        LeaveCreate(label="PTO", start_date=THURSDAY, end_date=THURSDAY + timedelta(days=2)),
    )

    assert await leave.holiday_dates(db, THURSDAY, THURSDAY + timedelta(days=2)) == set()
    assert await _due(db, policy, item_id) == datetime(2026, 7, 2, 10, 0)


async def test_without_the_provider_the_clock_is_unchanged(db, admin):
    """`slas` with the leave plugin absent (or disabled at runtime, which is the
    same withdrawal): no providers, no dates, byte-identical behaviour — even
    with the holiday rows still sitting in the database."""
    from radd.modules.leave import plugin as leave_plugin

    project = await projects_service.create_project(db, ProjectCreate(key="SLN", name="SLA None"))
    policy = await _day_policy(db, admin, project.id)
    item_id = await _filed_item(db, admin, project.id)
    await _holiday(db, admin, THURSDAY, THURSDAY)
    assert await _due(db, policy, item_id) == datetime(2026, 7, 3, 10, 0)

    registries.unregister_plugin(leave_plugin)
    try:
        assert registries.providers(Socket.NON_WORKING_DAYS) == {}
        assert await calendar.non_working_dates(db, THURSDAY, THURSDAY) == frozenset()
        assert await _due(db, policy, item_id) == datetime(2026, 7, 2, 10, 0)
    finally:
        registries.register_plugin(leave_plugin)


async def test_a_broken_calendar_does_not_stop_the_clock(db, admin):
    """A provider that raises is skipped, not propagated: a broken holiday
    calendar must never be the reason breaches stop being detected."""
    from radd.kernel import IntegrationSpec

    class Exploding:
        async def non_working_dates(self, session, start, end):
            raise RuntimeError("calendar service down")

    spec = IntegrationSpec(Socket.NON_WORKING_DAYS, "exploding", impl=Exploding())
    registries.integrations[(spec.socket, spec.name)] = spec
    try:
        # The surviving provider still answers; the broken one is logged away.
        await _holiday(db, admin, THURSDAY, THURSDAY)
        assert await calendar.non_working_dates(db, THURSDAY, THURSDAY) == frozenset({THURSDAY})
    finally:
        registries.integrations.pop((spec.socket, spec.name), None)
