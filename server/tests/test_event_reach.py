"""RADD-1320: the events automations could not see, and the subjects they could
not reach. One test per event, each against live Postgres (rolled back).

- a subject ref on the itemless events (project/user/team/cycle/release/leave);
- `user.created`/`user.updated` from the directory sign-in paths;
- `item.watched` from auto-watch (`auto: true`);
- `sla.met`;
- `form.submitted`, and `origin` on `item.created`;
- the host author on VCS ref triggers.
"""

import uuid
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.clock import utcnow
from radd.config import settings
from radd.kernel import load_plugins
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.automations.gates import project_is
from radd.modules.automations.conditions import EventFacts
from radd.modules.events.models import Event
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemOrigin
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate, ProjectUpdate


@pytest.fixture
async def db():
    load_plugins(settings.modules)
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def world(db):
    admin = User(email=f"subj-{uuid.uuid4().hex[:8]}@example.com", name="Ada", instance_role=InstanceRole.ADMIN.value)
    db.add(admin)
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SJ{uuid.uuid4().hex[:4].upper()}", name="Subjects")
    )
    return admin, project


async def _head(db) -> int:
    return (await db.execute(select(Event.id).order_by(Event.id.desc()).limit(1))).scalar() or 0


async def _events(db, head: int, event_type: str) -> list[Event]:
    rows = await db.execute(select(Event).where(Event.id > head, Event.event_type == event_type).order_by(Event.id))
    return list(rows.scalars())


async def test_project_is_x_matches_project_updated(db, world):
    """The audit's example: "Project is X" answered False on "Project updated"."""
    admin, project = world
    head = await _head(db)
    await projects_service.update_project(db, project, ProjectUpdate(name="Renamed"), actor_id=admin.id)
    [event] = await _events(db, head, "project.updated")
    assert event.payload["project"]["key"] == project.key
    facts = EventFacts(event_type=event.event_type, actor_id=None, actor_email=None, actor_name=None, payload=event.payload)
    assert project_is(facts, {"projects": [project.key]}) is True


async def test_user_team_cycle_and_release_events_carry_their_subject(db, world):
    from radd.modules.cycles import service as cycles
    from radd.modules.cycles.schemas import CycleCreate
    from radd.modules.releases import service as releases
    from radd.modules.releases.schemas import ReleaseCreate
    from radd.modules.teams import service as teams
    from radd.modules.teams.schemas import TeamCreate

    admin, project = world
    head = await _head(db)
    team = await teams.create_team(db, TeamCreate(name=f"t-{uuid.uuid4().hex[:6]}"), admin.id)
    cycle = await cycles.create_cycle(db, CycleCreate(name=f"c-{uuid.uuid4().hex[:6]}"), date(2026, 9, 25), admin.id)
    release = await releases.create_release(
        db, ReleaseCreate(project_id=project.id, name="One", version=f"9.{uuid.uuid4().int % 1000}.0"), admin.id
    )

    [t] = await _events(db, head, "team.created")
    assert t.payload["team"] == {"id": str(team.id), "name": team.name}
    [c] = await _events(db, head, "cycle.created")
    assert c.payload["cycle"]["id"] == str(cycle.id)
    [r] = await _events(db, head, "release.created")
    assert r.payload["release"]["version"] == release.version


async def test_leave_names_whose_leave_it_was_both_ways(db, world):
    from radd.modules.leave import service as leave
    from radd.modules.leave.schemas import LeaveCreate

    admin, _project = world
    head = await _head(db)
    period = await leave.create(
        db, admin, LeaveCreate(label="Off", start_date=date(2026, 10, 1), end_date=date(2026, 10, 2))
    )
    await leave.remove(db, admin, period.id)
    [created] = await _events(db, head, "leave.created")
    [deleted] = await _events(db, head, "leave.deleted")
    assert created.payload["user"]["id"] == str(admin.id)
    # It named nobody at all before RADD-1320.
    assert deleted.payload["user"]["id"] == str(admin.id)


async def test_ldap_sign_in_creates_then_updates_through_auth(db, monkeypatch):
    from radd.modules.ldap import service as ldap
    from radd.modules.ldap.types import DirectoryUser

    monkeypatch.setattr(settings, "ldap_auto_provision", True)
    # The directory has a role opinion only when admin groups are configured (RADD-1416).
    monkeypatch.setattr(ldap, "_conn", replace(ldap._conn, admin_groups="Radd Admins"))
    email = f"dir-{uuid.uuid4().hex[:8]}@example.com"
    head = await _head(db)
    user = await ldap.provision(db, DirectoryUser(username="dir", email=email, name="Dee", is_admin=False))
    [created] = await _events(db, head, "user.created")
    assert created.payload["user"]["email"] == email
    assert await _events(db, head, "user.updated") == [], "a first login is a creation, not an update"

    # The directory promotes them: a silent write before RADD-1320.
    head = await _head(db)
    await ldap.provision(db, DirectoryUser(username="dir", email=email, name="Dee", is_admin=True))
    [updated] = await _events(db, head, "user.updated")
    assert {"field": "instance_role", "from": "member", "to": "admin"} in [
        {k: c[k] for k in ("field", "from", "to")} for c in updated.payload["changes"]
    ]
    assert updated.payload["user"]["id"] == str(user.id)

    # Nothing changed on the next login: nothing emitted.
    head = await _head(db)
    await ldap.provision(db, DirectoryUser(username="dir", email=email, name="Dee", is_admin=True))
    assert await _events(db, head, "user.updated") == []


async def test_auto_watch_emits_once_and_says_so(db, world):
    from radd.modules.notify import service as notify

    admin, project = world
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="watch me"), admin)
    other = User(email=f"w-{uuid.uuid4().hex[:8]}@example.com", name="Wes", instance_role=InstanceRole.MEMBER.value)
    db.add(other)
    await db.flush()
    head = await _head(db)
    assert await notify.add_watchers(db, item.id, [other.id]) == [other.id]
    assert await notify.add_watchers(db, item.id, [other.id]) == []  # already watching: quiet
    [watched] = await _events(db, head, "item.watched")
    assert watched.payload["auto"] is True
    assert watched.payload["user"]["id"] == str(other.id)
    assert watched.payload["item"]["id"] == str(item.id)


async def test_sla_met_fires_once_with_on_time(db, world):
    from radd.modules.slas import evaluation
    from radd.modules.slas.timers import TimerStatus
    from radd.modules.slas.types import SlaKind

    admin, project = world
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="answer me"), admin)
    policy = SimpleNamespace(id=uuid.uuid4(), name="Gold", warning_minutes=None)
    now = utcnow()
    live = TimerStatus(due_at=now + timedelta(hours=1), met_at=None, breached=False, paused=False, remaining_seconds=3600)
    met = TimerStatus(due_at=now + timedelta(hours=1), met_at=now, breached=False, paused=False, remaining_seconds=None)
    refs = {item.id: {"id": str(item.id)}}

    # sla_item_states has an FK to sla_policies — use a real policy row id.
    from radd.modules.slas.models import SlaPolicy

    row = SlaPolicy(name="Gold", project_id=project.id)
    db.add(row)
    await db.flush()
    policy.id = row.id

    head = await _head(db)
    await evaluation.sync_states(db, policy, {item.id: {SlaKind.RESPONSE: (60, live)}}, refs)
    assert await _events(db, head, "sla.met") == []
    await evaluation.sync_states(db, policy, {item.id: {SlaKind.RESPONSE: (60, met)}}, refs)
    await evaluation.sync_states(db, policy, {item.id: {SlaKind.RESPONSE: (60, met)}}, refs)
    [event] = await _events(db, head, "sla.met")
    assert event.payload["kind"] == SlaKind.RESPONSE.value
    assert event.payload["on_time"] is True
    assert event.payload["item"]["id"] == str(item.id)


async def test_a_form_submission_fires_form_submitted_and_the_item_says_where_from(db, world):
    from radd.modules.forms import service as forms
    from radd.modules.forms.schemas import FormCreate, FormSubmit

    admin, project = world
    form = await forms.create_form(db, FormCreate(project_id=project.id, name="Bug report"), admin)
    head = await _head(db)
    item = await forms.submit_form(db, form.id, FormSubmit(title="It broke"), admin)

    [submitted] = await _events(db, head, "form.submitted")
    assert submitted.payload["form"] == {"id": str(form.id), "name": "Bug report"}
    assert submitted.payload["item"]["id"] == str(item.id)
    assert submitted.payload["project"]["key"] == project.key
    assert submitted.payload["user"]["id"] == str(admin.id)
    [created] = await _events(db, head, "item.created")
    assert created.payload["origin"] == ItemOrigin.FORM.value


async def test_item_origin_is_absent_for_a_person_and_derived_for_an_automation(db, world):
    from radd.modules.events import service as events

    admin, project = world
    head = await _head(db)
    await items_service.create_item(db, ItemCreate(project_id=project.id, title="typed"), admin)
    with events.automated():
        await items_service.create_item(db, ItemCreate(project_id=project.id, title="automated"), admin)
    with items_service.creating_from(ItemOrigin.EMAIL):
        await items_service.create_item(db, ItemCreate(project_id=project.id, title="mailed"), admin)
    origins = [e.payload["origin"] for e in await _events(db, head, "item.created")]
    assert origins == [None, ItemOrigin.AUTOMATION.value, ItemOrigin.EMAIL.value]


def test_host_author_reads_each_hosts_shape():
    from radd.modules.vcs.triggers import host_author

    conn = uuid.uuid4()
    gitlab_push = host_author({"user_username": "ada", "user_email": "ada@x.io"}, conn)
    gitlab_mr = host_author({"user": {"username": "bo", "email": "bo@x.io"}}, conn)
    github_push = host_author({"sender": {"login": "cy"}, "pusher": {"email": "cy@x.io"}}, conn)
    forgejo = host_author({"sender": {"login": "di", "email": "di@x.io"}}, conn)
    assert (gitlab_push.username, gitlab_push.email) == ("ada", "ada@x.io")
    assert (gitlab_mr.username, gitlab_mr.email) == ("bo", "bo@x.io")
    assert (github_push.username, github_push.email) == ("cy", "cy@x.io")
    assert (forgejo.username, forgejo.email) == ("di", "di@x.io")
    assert host_author({}, conn) is None
