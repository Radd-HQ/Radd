"""The resolution notice (RADD-982) — driven through the real services against
live Postgres in a rolled-back transaction (the `test_csat` idiom).

The audit finding this closes: on a default install nothing told a requester
their ticket was resolved. The only message that ever said so was the CSAT
survey, which is per-project opt-in and off by default.

Three properties are load-bearing and each is pinned below, because each one
has an obvious wrong implementation that would look like it worked:

* it announces ENTERING done, so a done→done move (spec 112's release sweep
  performs one on every shipped item) mails nobody a second time;
* it YIELDS to CSAT, because the survey's own first line announces the
  resolution and two messages for one event is worse than the silence;
* it reaches every contact, not only the primary one (RADD-980's plural seam),
  and never an address belonging to an active user.

Events come from REAL `item.updated` emissions so the payload-shape assumption
— a `changes` diff plus a post-mutation state embed — stays verified rather
than asserted against a literal this file wrote.
"""

import uuid

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.events import service as events_service
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEntity, ItemEvent
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.mailintake import outbound, resolved, service as mail_service
from radd.modules.mailintake.models import MailSender
from radd.modules.mailintake.reply import Recipient
from radd.modules.mailintake.types import MailRecipientKind
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope
from radd.modules.workflow import service as workflow_service
from radd.modules.workflow.schemas import StateCreate
from radd.modules.workflow.types import StateCategory

CONTACT = "jane@vip-customer.com"
SECOND_CONTACT = "priya@vip-customer.com"


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
        email=f"desk-{uuid.uuid4().hex[:8]}@example.com",
        name="Desk Agent",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def project(db):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"RS{uuid.uuid4().hex[:4].upper()}", name="Service desk")
    )


@pytest.fixture
async def relay(db, monkeypatch):
    """Somewhere to send FROM, so `outbound_configured` is true — and rows
    disabled so a sender another test committed cannot be what answers.

    The consumer's gate is shared by both messages it ships; without this the
    resolution tests would pass or fail on whatever else is in the database.
    """
    await db.execute(update(MailSender).values(enabled=False))
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")


async def _state(db, project, category: StateCategory):
    states = await workflow_service.list_states(db, project.id)
    return next(s for s in states if s.category == category.value)


async def _move(db, admin, project, item_id, state):
    """Move the item and return the REAL `item.updated` event it emitted."""
    await items_service.update_item(db, item_id, ItemUpdate(state_id=state.id), admin)
    rows = await events_service.query_events(
        db,
        entity_type=ItemEntity.ITEM.value,
        entity_id=str(item_id),
        event_types=[ItemEvent.UPDATED.value],
        limit=1,
    )
    return rows[0]


async def _resolve(db, admin, project, item_id):
    return await _move(db, admin, project, item_id, await _state(db, project, StateCategory.DONE))


async def _ticket(db, admin, project, *, contacts=(CONTACT,)):
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="printer on fire"), admin
    )
    for address in contacts:
        await mail_service.upsert_contact(db, item.id, email=address, name="Jane")
    return item


# --- the pure guard ---------------------------------------------------------

DONE_CATEGORIES = {"Todo": "backlog", "Waiting for release": "done", "Done": "done"}


def _payload(*, moved_from: str, to_category: str, state_name: str = "Done") -> dict:
    return {
        "changes": [{"field": "state", "from": moved_from, "to": state_name}],
        "item": {"state": {"name": state_name, "category": to_category}},
    }


def test_entering_done_from_outside_it_is_the_whole_guard():
    done = StateCategory.DONE.value
    assert resolved.entered_done(_payload(moved_from="Todo", to_category=done), DONE_CATEGORIES)
    # The move that must NOT announce: already done, moving within done. Spec
    # 112's release sweep does exactly this to every shipped item, and csat's
    # `moved_to_done` passes on it — saved only by its unique survey row, which
    # this feature deliberately does not have.
    assert not resolved.entered_done(
        _payload(moved_from="Waiting for release", to_category=done), DONE_CATEGORIES
    )
    # Landed somewhere that is not done.
    assert not resolved.entered_done(
        _payload(moved_from="Todo", to_category=StateCategory.IN_PROGRESS.value),
        DONE_CATEGORIES,
    )
    # An edit that moved no state at all (an assignee change on a done item).
    assert not resolved.entered_done(
        {"changes": [{"field": "assignee"}], "item": {"state": {"category": done}}},
        DONE_CATEGORIES,
    )
    assert not resolved.entered_done({}, DONE_CATEGORIES)  # create-shaped payload


def test_a_from_state_nobody_recognises_announces_rather_than_swallowing():
    """The diff records the state's NAME at write time, so a state renamed
    since resolves to nothing here. Read as "was not done": announcing twice is
    recoverable, never announcing is the defect this feature exists to end."""
    assert resolved.entered_done(
        _payload(moved_from="Renamed away", to_category=StateCategory.DONE.value),
        DONE_CATEGORIES,
    )


def test_the_cheap_half_answers_without_the_project_categories():
    """`resolved_now` is what the consumer runs on every `item.updated` on the
    stream; `entered_done` costs a query and runs on almost none of them."""
    assert resolved.resolved_now(_payload(moved_from="Todo", to_category=StateCategory.DONE.value))
    assert not resolved.resolved_now(
        _payload(moved_from="Todo", to_category=StateCategory.IN_PROGRESS.value)
    )
    assert not resolved.resolved_now({})


# --- what gets planned ------------------------------------------------------


async def test_resolving_plans_a_notice_for_every_contact(db, admin, project, relay):
    item = await _ticket(db, admin, project, contacts=(CONTACT, SECOND_CONTACT))
    event = await _resolve(db, admin, project, item.id)

    notice = await resolved.plan(db, event)
    assert notice is not None
    assert {r.email for r in notice.recipients} == {CONTACT, SECOND_CONTACT}
    assert notice.subject == f"[{item.key}] Your request has been resolved"
    # Its own sentence, not a `Re:` — the transport is told to keep it.
    assert notice.pin_subject is True and notice.comment_id is None
    assert notice.state_name == (await _state(db, project, StateCategory.DONE)).name


async def test_the_notice_names_the_state_the_ticket_landed_in(db, admin, project, relay):
    """A desk with "Resolved" and "Closed" means two different things by them,
    and the requester is the one person who cannot look the difference up."""
    item = await _ticket(db, admin, project)
    closed = await workflow_service.create_state(
        db,
        StateCreate(project_id=project.id, name="Closed", category=StateCategory.DONE.value),
    )
    event = await _move(db, admin, project, item.id, closed)

    notice = await resolved.plan(db, event)
    assert notice is not None and notice.state_name == "Closed"
    message = notice.render(notice.recipients[0])
    assert "Closed" in message.text and "Closed" in message.html


async def test_a_done_to_done_move_plans_nothing(db, admin, project, relay):
    """The release sweep's shape: Waiting for release → Done, both in the done
    category. The customer was told when it entered the first one."""
    item = await _ticket(db, admin, project)
    waiting = await workflow_service.create_state(
        db,
        StateCreate(
            project_id=project.id, name="Waiting for release", category=StateCategory.DONE.value
        ),
    )
    first = await _move(db, admin, project, item.id, waiting)
    assert await resolved.plan(db, first) is not None

    shipped = await _move(db, admin, project, item.id, await _state(db, project, StateCategory.DONE))
    assert await resolved.plan(db, shipped) is None


async def test_reopening_says_nothing_and_re_resolving_says_it_again(db, admin, project, relay):
    """A reopen is not an event the requester needs a message about; a second
    resolution IS, and is announced deliberately — which is why there is no
    once-per-lifetime row here."""
    item = await _ticket(db, admin, project)
    await _resolve(db, admin, project, item.id)

    reopened = await _move(
        db, admin, project, item.id, await _state(db, project, StateCategory.IN_PROGRESS)
    )
    assert await resolved.plan(db, reopened) is None

    again = await _resolve(db, admin, project, item.id)
    assert await resolved.plan(db, again) is not None


async def test_a_ticket_with_no_external_contact_plans_nothing(db, admin, project, relay):
    """An issue an agent typed in has nobody outside to tell. `notify` reaches
    the users; this leg is only ever the people with no account."""
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="internal chore"), admin
    )
    event = await _resolve(db, admin, project, item.id)
    assert await resolved.plan(db, event) is None


async def test_the_setting_turns_it_off_for_one_project(db, admin, project, relay):
    item = await _ticket(db, admin, project)
    await settings_service.set_value(
        db, SettingKey.MAIL_SEND_RESOLVED, SettingScope.PROJECT, project.id, False
    )
    event = await _resolve(db, admin, project, item.id)
    assert await resolved.plan(db, event) is None


async def test_it_is_on_by_default(db, admin, project, relay):
    """Unlike CSAT. A desk that has to be configured before it says "done" says
    it on no instance at all, which was the finding."""
    assert settings.mail_send_resolved is True
    item = await _ticket(db, admin, project)
    event = await _resolve(db, admin, project, item.id)
    assert await resolved.plan(db, event) is not None


async def test_it_yields_to_the_csat_survey(db, admin, project, relay):
    """One message, not two: the survey's first line already announces the
    resolution, and it additionally asks a question the notice cannot."""
    from radd.modules.csat import service as csat_service

    item = await _ticket(db, admin, project)
    await settings_service.set_value(
        db, SettingKey.CSAT_ENABLED, SettingScope.PROJECT, project.id, True
    )
    assert await csat_service.announces_resolution(db, project.id) is True

    event = await _resolve(db, admin, project, item.id)
    assert await resolved.plan(db, event) is None


async def test_a_disabled_csat_answers_by_absence_and_the_notice_goes(db, admin, project, relay, monkeypatch):
    """`weak_depends` does not block disabling csat (only `depends_on` does), so
    the reach has to survive the plugin being gone — and "gone" must mean NOT
    ANNOUNCING, not an ImportError and not a stale True off a setting row that
    nothing reads any more."""
    from radd.kernel import registries

    item = await _ticket(db, admin, project)
    await settings_service.set_value(
        db, SettingKey.CSAT_ENABLED, SettingScope.PROJECT, project.id, True
    )
    without_csat = {k: v for k, v in registries.plugins.items() if k != "csat"}
    monkeypatch.setattr(registries, "plugins", without_csat)

    event = await _resolve(db, admin, project, item.id)
    assert await resolved.plan(db, event) is not None


# --- what it says -----------------------------------------------------------


def test_the_rendered_notice_carries_the_ticket_the_state_and_the_link():
    from radd import mailrender

    notice = resolved.ResolvedNotice(
        item_id=uuid.uuid4(),
        subject="[SD-7] Your request has been resolved",
        state_name="Done",
        item=mailrender.ItemMail(key="SD-7", title="printer on fire", base_url="https://radd.test"),
        recipients=(Recipient(CONTACT, "Jane", MailRecipientKind.REQUESTER),),
    )
    message = notice.render(notice.recipients[0])
    for half in (message.text, message.html):
        assert "SD-7" in half
        assert "Done" in half
        assert "https://radd.test/issues/SD-7" in half
        # The footer says why this address is hearing from us at all.
        assert "you contacted us about SD-7" in half
    # Both halves, always — a multipart message whose halves drift is what
    # `mailrender` exists to prevent.
    assert message.html.startswith("<html>")


def test_the_body_never_becomes_markup():
    """A title is user text and lands in someone's mail client."""
    from radd import mailrender

    notice = resolved.ResolvedNotice(
        item_id=uuid.uuid4(),
        subject="s",
        state_name="Done",
        item=mailrender.ItemMail(
            key="SD-8", title="<script>alert(1)</script>", base_url="https://radd.test"
        ),
        recipients=(Recipient(CONTACT, "Jane", MailRecipientKind.REQUESTER),),
    )
    html = notice.render(notice.recipients[0]).html
    assert "<script>" not in html and "&lt;script&gt;" in html


# --- the wire to the consumer -----------------------------------------------


async def test_the_outbound_consumer_claims_the_resolution_event(db, admin, project, relay):
    """The plan is only reachable if `outbound._plan` dispatches on it — the one
    line that connects this file to a running instance, and the kind of wire a
    unit test on the planner alone would never touch."""
    item = await _ticket(db, admin, project)
    event = await _resolve(db, admin, project, item.id)

    plan = await outbound._plan(db, event)
    assert isinstance(plan, resolved.ResolvedNotice)
    # Everything `_deliver` reads off a plan, present on this one.
    assert plan.item_id == item.id and plan.recipients and plan.subject
    assert plan.pin_subject is True and plan.comment_id is None


async def test_with_nowhere_to_send_from_the_consumer_plans_nothing(db, admin, project, monkeypatch):
    """The shared gate: the cursor still advances, so configuring a sender later
    replays no backlog into a customer's mailbox."""
    await db.execute(update(MailSender).values(enabled=False))
    monkeypatch.setattr(settings, "smtp_host", "")
    item = await _ticket(db, admin, project)
    event = await _resolve(db, admin, project, item.id)
    assert await outbound._plan(db, event) is None
