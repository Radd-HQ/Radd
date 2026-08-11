"""SLA depth (spec 63): first-match resolution against the DB, the list/board
batch compute (shape + permission filtering), and the weekly SLA report.

Live Postgres inside a rolled-back transaction, like tests/test_reporting.py.
The pure timer/first-match math lives in tests/test_sla.py.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.enums import Priority
from radd.modules.items.schemas import ItemCreate
from radd.modules.reporting import service as reporting
from radd.modules.slas import evaluation, service as slas
from radd.modules.slas.models import SlaItemState
from radd.modules.slas.schemas import PolicyCreate, PolicyUpdate
from radd.modules.slas.types import SlaKind
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"sla-{uuid.uuid4().hex[:8]}@example.com",
        name="SLA Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _project(db, run: str, key: str):
    return await projects_service.create_project(
        db, ProjectCreate(key=key, name=f"SLA {key}")
    )


async def _item(db, admin, project_id, priority=Priority.NORMAL, type_id=None):
    read = await items_service.create_item(
        db,
        ItemCreate(
            project_id=project_id, title=f"sla {priority}", priority=priority, type_id=type_id
        ),
        admin,
    )
    return (await items_service.items_by_ids(db, [read.id]))[read.id]


async def _types(db, project_id) -> dict[str, uuid.UUID]:
    """{name: id} of the project's seeded issue types (Task/Bug/Story/…)."""
    from radd.modules.itemtypes import service as itemtypes

    return {t.name: t.id for t in await itemtypes.list_types(db, project_id)}


async def test_matched_policy_first_match_in_db(db, admin):
    run = uuid.uuid4().hex[:6]
    project = await _project(db, run, "SLD")
    p1 = await slas.create_policy(
        db,
        PolicyCreate(
            project_id=project.id,
            name="P1 fast",
            response_minutes=60,
            priorities=[Priority.BLOCKER],
            position=0,
        ),
        actor_id=admin.id,
    )
    standard = await slas.create_policy(
        db,
        PolicyCreate(project_id=project.id, name="Standard", response_minutes=480, position=1),
        actor_id=admin.id,
    )
    urgent = await _item(db, admin, project.id, Priority.BLOCKER)
    normal = await _item(db, admin, project.id)

    assert (await slas.matched_policy(db, urgent)).id == p1.id
    assert (await slas.matched_policy(db, normal)).id == standard.id
    # Reordering flips the winner for blockers (the catch-all now shadows P1).
    await slas.update_policy(db, standard.id, PolicyUpdate(position=0), actor_id=admin.id)
    await slas.update_policy(db, p1.id, PolicyUpdate(position=1), actor_id=admin.id)
    assert (await slas.matched_policy(db, urgent)).id == standard.id
    # A disabled policy never matches: normal items fall through P1's priority
    # filter and, with the catch-all off, end up governed by nothing.
    await slas.update_policy(db, standard.id, PolicyUpdate(enabled=False), actor_id=admin.id)
    assert (await slas.matched_policy(db, normal)) is None


async def test_policies_match_by_issue_type(db, admin):
    """RADD-1043: a desk answers a Bug and a Story on different promises.

    Priority could not express that — a normal-priority outage and a
    normal-priority request are the same tier — so the filter is the type, with
    the priority filter's semantics exactly: empty means every type.
    """
    project = await _project(db, uuid.uuid4().hex[:6], "SLT")
    types = await _types(db, project.id)
    bugs = await slas.create_policy(
        db,
        PolicyCreate(
            project_id=project.id,
            name="Bugs fast",
            response_minutes=30,
            issue_type_ids=[types["Bug"]],
            position=0,
        ),
        actor_id=admin.id,
    )
    everything = await slas.create_policy(
        db,
        PolicyCreate(
            project_id=project.id, name="Everything else", response_minutes=480, position=1
        ),
        actor_id=admin.id,
    )

    bug = await _item(db, admin, project.id, type_id=types["Bug"])
    story = await _item(db, admin, project.id, type_id=types["Story"])
    assert (await slas.matched_policy(db, bug)).id == bugs.id
    assert (await slas.matched_policy(db, story)).id == everything.id

    # A type filter narrows only itself: with the catch-all gone, a Story is
    # governed by nothing rather than falling into the Bug policy.
    await slas.update_policy(db, everything.id, PolicyUpdate(enabled=False), actor_id=admin.id)
    assert (await slas.matched_policy(db, story)) is None
    # Clearing the filter (explicit []) restores "every type" — the round trip
    # the form performs.
    await slas.update_policy(db, bugs.id, PolicyUpdate(issue_type_ids=[]), actor_id=admin.id)
    assert bugs.issue_type_ids == []
    assert (await slas.matched_policy(db, story)).id == bugs.id


async def test_issue_type_filter_reaches_the_batch_engine(db, admin):
    """The same first-match walk the list/board chips and the engine loop run:
    two policies, one project, different types → different targets per item."""
    project = await _project(db, uuid.uuid4().hex[:6], "SLE")
    types = await _types(db, project.id)
    await slas.create_policy(
        db,
        PolicyCreate(
            project_id=project.id,
            name="Bugs fast",
            response_minutes=30,
            issue_type_ids=[types["Bug"]],
            position=0,
        ),
        actor_id=admin.id,
    )
    await slas.create_policy(
        db,
        PolicyCreate(
            project_id=project.id,
            name="Features later",
            response_minutes=480,
            issue_type_ids=[types["Feature"]],
            position=1,
        ),
        actor_id=admin.id,
    )
    bug = await _item(db, admin, project.id, type_id=types["Bug"])
    feature = await _item(db, admin, project.id, type_id=types["Feature"])
    task = await _item(db, admin, project.id, type_id=types["Task"])

    result = await evaluation.batch_sla(db, admin, [bug.id, feature.id, task.id])
    assert {t.policy_name for t in result[bug.id]} == {"Bugs fast"}
    assert {t.policy_name for t in result[feature.id]} == {"Features later"}
    # No policy covers a Task, so it gets no chips at all (not the first policy).
    assert result.get(task.id, []) == []


async def test_business_window_validation(db, admin):
    run = uuid.uuid4().hex[:6]
    project = await _project(db, run, "SLW")
    with pytest.raises(ConflictError):
        await slas.create_policy(
            db,
            PolicyCreate(
                project_id=project.id,
                name="half a window",
                response_minutes=60,
                business_start_minute=540,
            ),
            actor_id=admin.id,
        )
    with pytest.raises(ConflictError):
        await slas.create_policy(
            db,
            PolicyCreate(
                project_id=project.id,
                name="inverted",
                response_minutes=60,
                business_start_minute=1050,
                business_end_minute=540,
            ),
            actor_id=admin.id,
        )


async def test_batch_sla_shape_and_permission_filtering(db, admin):
    run = uuid.uuid4().hex[:6]
    project_a = await _project(db, run, "SLA")
    project_b = await _project(db, run, "SLB")
    await slas.create_policy(
        db,
        PolicyCreate(
            project_id=project_a.id,
            name="A standard",
            response_minutes=60,
            resolution_minutes=480,
        ),
        actor_id=admin.id,
    )
    await slas.create_policy(
        db,
        PolicyCreate(project_id=project_b.id, name="B standard", response_minutes=60),
        actor_id=admin.id,
    )
    mine = await _item(db, admin, project_a.id)
    theirs = await _item(db, admin, project_b.id)

    # Spec 86: any ACTIVE user reads every project; an INACTIVE one reads none.
    actor = User(
        email=f"sla-actor-{run}@example.com", name="Agent", instance_role=InstanceRole.MEMBER.value
    )
    inactive = User(
        email=f"sla-inactive-{run}@example.com",
        name="Gone",
        instance_role=InstanceRole.MEMBER.value,
        active=False,
    )
    db.add_all([actor, inactive])
    await db.flush()

    result = await evaluation.batch_sla(db, actor, [mine.id, theirs.id, uuid.uuid4()])
    # Unknown items are filtered out, not erred on; both projects are readable.
    assert set(result) == {mine.id, theirs.id}
    assert await evaluation.batch_sla(db, inactive, [mine.id, theirs.id]) == {}
    timers = result[mine.id]
    assert {t.kind for t in timers} == {SlaKind.RESPONSE, SlaKind.RESOLUTION}
    for timer in timers:
        assert timer.policy_name == "A standard"
        assert timer.met_at is None and timer.breached is False and timer.paused is False
        assert timer.due_at is not None and timer.remaining_seconds > 0


async def test_sla_report_smoke(db, admin):
    run = uuid.uuid4().hex[:6]
    project = await _project(db, run, "SLR")
    policy = await slas.create_policy(
        db,
        PolicyCreate(
            project_id=project.id, name="Report", response_minutes=60, resolution_minutes=480
        ),
        actor_id=admin.id,
    )
    met = await _item(db, admin, project.id)
    late = await _item(db, admin, project.id)
    db.add(
        SlaItemState(
            item_id=met.id,
            policy_id=policy.id,
            response_met_at=met.created_at + timedelta(minutes=30),
            resolution_met_at=met.created_at + timedelta(hours=4),
        )
    )
    db.add(
        SlaItemState(
            item_id=late.id,
            policy_id=policy.id,
            response_breached_at=late.created_at + timedelta(minutes=61),
        )
    )
    await db.flush()

    # Spec 86: project_id=None is now truly global — scope to this test's project.
    buckets = (await reporting.sla_report(db, project.id, weeks=2)).buckets
    assert len(buckets) == 2
    assert sum(b.items for b in buckets) == 2
    assert sum(b.response_met for b in buckets) == 1
    assert sum(b.response_breached for b in buckets) == 1
    assert sum(b.resolution_met for b in buckets) == 1
    week = next(b for b in buckets if b.items)
    assert week.breach_rate == pytest.approx(0.5)
    assert week.avg_response_seconds == pytest.approx(30 * 60)
    assert week.avg_resolution_seconds == pytest.approx(4 * 3600)
    # Project scoping: an unrelated project sees an all-zero window.
    empty = (await reporting.sla_report(db, uuid.uuid4(), weeks=2)).buckets
    assert sum(b.items for b in empty) == 0


def _raw(*, sender, subject, body, message_id, in_reply_to=None) -> bytes:
    from email.message import EmailMessage

    m = EmailMessage()
    m["Subject"] = subject
    m["From"] = sender
    m["To"] = "help@radd-hq.com"
    m["Message-ID"] = message_id
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
    m.set_content(body)
    return m.as_bytes()


async def test_an_agents_emailed_reply_satisfies_the_response_target(db, admin):
    """RADD-981, at the seam that decides whether an answer COUNTS.

    The first-response feed skips the reporter (answering yourself is not a
    response) and the SYSTEM actor (an automation's acknowledgement is not one
    either). Every inbound-mail comment used to be SYSTEM-authored — so an agent
    who answered a customer BY EMAIL, the ordinary way a service desk works,
    left the response timer running until it breached, while the same words
    typed into the UI stopped it. Nothing reported that anywhere; the breach
    simply arrived.
    """
    from radd.modules.mailintake import intake, parsing, threading as mail_threading
    from radd.modules.mailintake.types import MailDirection

    run = uuid.uuid4().hex[:6]
    project = await _project(db, run, f"SM{run[:2].upper()}")
    policy = await slas.create_policy(
        db,
        PolicyCreate(project_id=project.id, name="Desk", response_minutes=60),
        actor_id=admin.id,
    )

    incoming = _raw(
        sender="Cass <cass@vip.example.com>",
        subject="Printer on fire",
        body="please help",
        message_id=f"<sla-in-{run}@ext>",
    )
    opened = await intake.accept(
        db,
        parsing.parse_email(incoming),
        raw=incoming,
        default_project_key=project.key,
        own_addresses={"help@radd-hq.com"},
    )
    assert opened.result is intake.Result.CREATED
    before = await evaluation.evaluate_items(db, policy, [opened.item_id])
    assert before[opened.item_id][SlaKind.RESPONSE][1].met_at is None

    # The agent replies to a notification about the ticket, so it threads on a
    # header — the ordinary shape, and the one the RADD-981 subject-key gate
    # leaves untouched.
    await mail_threading.record(
        db,
        message_id=f"<sla-out-{run}@radd>",
        item_id=opened.item_id,
        direction=MailDirection.OUTBOUND,
    )
    answer = _raw(
        sender=f"Ada Agent <{admin.email}>",
        subject="Re: Printer on fire",
        body="Engineer dispatched.",
        message_id=f"<sla-reply-{run}@ext>",
        in_reply_to=f"<sla-out-{run}@radd>",
    )
    replied = await intake.accept(
        db,
        parsing.parse_email(answer),
        raw=answer,
        default_project_key=project.key,
        own_addresses={"help@radd-hq.com"},
    )
    assert replied.item_id == opened.item_id

    after = await evaluation.evaluate_items(db, policy, [opened.item_id])
    assert after[opened.item_id][SlaKind.RESPONSE][1].met_at is not None
