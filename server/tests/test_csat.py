"""CSAT surveys (spec 65), driven through the real services against live
Postgres in a rolled-back transaction (test_public_forms idiom):

- sender decision: setting off / SMTP off / no recipient → skip; the mail
  contact beats the reporter; one survey per item lifetime (reopen→re-resolve
  never resends). Events come from REAL item.updated emissions so the payload
  shape assumption (changes diff + state embed w/ category) stays verified.
- public flow: unknown token 404, rating bounds 422, responded_at stamped once,
  re-submits allowed (latest wins), csat.responded emitted.
- report: csat_avg/csat_count ride the /reports/sla buckets by responded week.

Send paths never touch the network: `radd.smtp.send_message` is monkeypatched.
"""

import uuid
from email.message import EmailMessage

import pytest
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd import smtp
from radd.config import settings
from radd.exceptions import NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole, UserSource
from radd.modules.csat import sender, service as csat_service
from radd.modules.csat.schemas import PublicCsatSubmit
from radd.modules.csat.types import CsatEvent
from radd.modules.events import service as events_service
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEntity, ItemEvent
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.mailintake import service as mail_service, threading as mail_threading
from radd.modules.mailintake.models import MailMessage, MailSender
from radd.modules.mailintake.types import MailDirection, MailEvent, MailSenderKind
from radd.modules.reporting import service as reporting
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope
from radd.modules.workflow import service as workflow_service
from radd.modules.workflow.types import StateCategory
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
        email=f"csat-{uuid.uuid4().hex[:8]}@example.com",
        name="CSAT Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def project(db):
    return await projects_service.create_project(
        db, ProjectCreate(key="CS65", name="Service desk")
    )


@pytest.fixture
async def no_senders(db):
    """Disable every `mail_senders` row already in the test database.

    Since RADD-983 the survey's guard is `outbound_configured`, which reads the
    TABLE as well as the environment — so a row some other module committed
    would otherwise decide whether these tests think mail is configured. Inside
    the transaction, so it rolls back with everything else.
    """
    await db.execute(update(MailSender).values(enabled=False))


@pytest.fixture
def smtp_on(monkeypatch):
    """The environment relay configured + captured — never a real send.

    Still the ENV leg on purpose: it is the configuration these decision tests
    were written against, and the rows-only leg (an instance with no
    `RADD_SMTP_*` at all, which is what radd-hq.com runs) gets its own test
    below rather than quietly replacing this one.
    """
    from radd import smtp as smtp_util

    sent: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(smtp_util, "send_message", lambda *a, **k: sent.append((a, k)))
    return sent


class _FakeSmtp:
    """Enough of smtplib.SMTP to capture what was composed, and by which relay
    — the connection details are the assertion when the point is that a ROW,
    not the environment, answered."""

    sent: list[EmailMessage] = []
    dialled: list[tuple] = []

    def __init__(self, host, port, **kwargs):
        type(self).dialled.append((host, port))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        pass

    def login(self, *args):
        pass

    def send_message(self, message):
        type(self).sent.append(message)


@pytest.fixture
def rows_only(monkeypatch):
    """A captured socket and NO environment relay (RADD-983).

    The whole point of the rows-only test: with `RADD_SMTP_HOST` empty, a
    message that goes out went out through a `mail_senders` row, so "the survey
    was sent" cannot be true by way of a fallback nobody configured.
    """
    _FakeSmtp.sent = []
    _FakeSmtp.dialled = []
    monkeypatch.setattr(smtp.smtplib, "SMTP", _FakeSmtp)
    monkeypatch.setattr(settings, "smtp_host", "")
    return _FakeSmtp


async def _enable_csat(db, project) -> None:
    await settings_service.set_value(
        db, SettingKey.CSAT_ENABLED, SettingScope.PROJECT, project.id, True
    )


async def _state(db, project, category: StateCategory):
    states = await workflow_service.list_states(db, project.id)
    return next(s for s in states if s.category == category.value)


async def _resolve(db, admin, project, item_id):
    """Move the item into a done-category state; return the REAL item.updated event."""
    done = await _state(db, project, StateCategory.DONE)
    await items_service.update_item(db, item_id, ItemUpdate(state_id=done.id), admin)
    rows = await events_service.query_events(
        db,
        entity_type=ItemEntity.ITEM.value,
        entity_id=str(item_id),
        event_types=[ItemEvent.UPDATED.value],
        limit=1,
    )
    return rows[0]


async def _item(db, admin, project, **kwargs):
    return await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="printer on fire", **kwargs), admin
    )


# --- sender decision ---


def test_moved_to_done_is_pure_over_the_payload():
    # `state` lives under `item` since RADD-922 — one addressing rule for every
    # item-scoped event.
    done = {"item": {"state": {"category": StateCategory.DONE.value}}}
    assert sender.moved_to_done({**done, "changes": [{"field": "state"}]})
    # No state change in the diff (e.g. an assignee edit while already done).
    assert not sender.moved_to_done({**done, "changes": [{"field": "assignee"}]})
    # State moved, but not INTO done.
    assert not sender.moved_to_done(
        {
            "changes": [{"field": "state"}],
            "item": {"state": {"category": StateCategory.IN_PROGRESS.value}},
        }
    )
    assert not sender.moved_to_done({})  # create-shaped payload: no changes at all


async def test_sender_skips_when_setting_off(db, admin, project, smtp_on):
    item = await _item(db, admin, project)
    event = await _resolve(db, admin, project, item.id)
    assert await sender.process_event(db, event) is None  # csat_enabled defaults False
    assert await csat_service.survey_for_item(db, item.id) is None


async def test_sender_skips_when_there_is_nowhere_to_send_from(
    db, admin, project, no_senders, monkeypatch
):
    """No `mail_senders` row AND no environment relay.

    The guard used to be `settings.smtp_host` alone (RADD-983), so an instance
    configured entirely through Settings → Email — sender rows, no
    `RADD_SMTP_*`, which is exactly how radd-hq.com runs — skipped every survey
    silently: the guard returned None, the cursor advanced and nothing was
    logged. `no_senders` is therefore load-bearing here: without it this test
    would pass for the wrong reason on a database where any relay row exists.
    """
    await _enable_csat(db, project)
    monkeypatch.setattr(settings, "smtp_host", "")
    item = await _item(db, admin, project)
    event = await _resolve(db, admin, project, item.id)
    assert await sender.process_event(db, event) is None
    assert await csat_service.survey_for_item(db, item.id) is None


async def test_sender_prefers_contact_over_reporter(db, admin, project, smtp_on):
    await _enable_csat(db, project)
    item = await _item(db, admin, project)  # reporter = admin
    await mail_service.upsert_contact(db, item.id, email="ext@example.com", name="Ext")
    event = await _resolve(db, admin, project, item.id)

    email = await sender.process_event(db, event)
    assert email is not None
    assert email.email == "ext@example.com" and email.name == "Ext"
    assert item.key in email.subject

    survey = await csat_service.survey_for_item(db, item.id)
    assert survey is not None and survey.rating is None and survey.responded_at is None
    # Five one-click links into the PUBLIC SPA page, one per rating.
    for rating in range(1, 6):
        assert f"{settings.app_base_url}/public/csat/{survey.token}?rating={rating}" in email.body
    requested = await events_service.query_events(
        db,
        entity_type=ItemEntity.ITEM.value,
        entity_id=str(item.id),
        event_types=[CsatEvent.REQUESTED.value],
    )
    assert len(requested) == 1 and requested[0].actor_id is None
    assert requested[0].payload["item"]["key"] == item.key


async def test_sender_falls_back_to_reporter_and_sends_once_only(db, admin, project, smtp_on):
    await _enable_csat(db, project)
    item = await _item(db, admin, project)  # no contact; reporter = admin (active)
    event = await _resolve(db, admin, project, item.id)

    email = await sender.process_event(db, event)
    assert email is not None and email.email == admin.email

    # Same event again (redelivery) and a reopen→re-resolve: both skipped.
    assert await sender.process_event(db, event) is None
    todo = await _state(db, project, StateCategory.TODO)
    await items_service.update_item(db, item.id, ItemUpdate(state_id=todo.id), admin)
    re_resolved = await _resolve(db, admin, project, item.id)
    assert sender.moved_to_done(re_resolved.payload)  # the event qualifies…
    assert await sender.process_event(db, re_resolved) is None  # …but the row guards


async def test_sender_skips_without_recipient(db, admin, project, smtp_on):
    await _enable_csat(db, project)
    # Explicit-null reporter (spec 62 idiom — an intake/public item) and no contact.
    item = await _item(db, admin, project, reporter_id=None)
    event = await _resolve(db, admin, project, item.id)
    assert await sender.process_event(db, event) is None
    assert await csat_service.survey_for_item(db, item.id) is None


async def test_a_service_account_reporter_is_never_surveyed(db, admin, project, smtp_on):
    """The reporter leg asked `reporter.active`, which a spec-113 SERVICE
    account and the system actor both pass (RADD-983).

    Not a hypothetical: the system actor is the reporter of every item mail
    intake creates, so the two accounts with no mailbox at all were among the
    likeliest to be surveyed — and both bounce, which is what got the relay
    rate-limited in the RADD-996 incident. The rule now comes from
    `mailintake.service.mailable_user`, stated once for CSAT and the send_email
    automation action alike.
    """
    await _enable_csat(db, project)
    robot = User(
        email=f"robot-{uuid.uuid4().hex[:8]}@service.radd.local",
        name="CI key",
        source=UserSource.SERVICE.value,
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(robot)
    await db.flush()
    item = await _item(db, admin, project, reporter_id=robot.id)
    event = await _resolve(db, admin, project, item.id)

    assert await sender.process_event(db, event) is None
    assert await csat_service.survey_for_item(db, item.id) is None


# --- delivery (RADD-983) ------------------------------------------------------

DESK_FROM = "support@radd-hq.com"


async def test_a_rows_only_instance_sends_the_survey_through_its_sender_row(
    db, admin, project, no_senders, rows_only
):
    """The whole of RADD-983 for CSAT, end to end and with the environment empty.

    Before it, the survey gated on `settings.smtp_host` and delivered through
    `radd.smtp` off the environment. On an instance configured only through
    Settings → Email that is TWO failures at once: the guard skips, and even if
    it had not, there is no relay to dial. Nothing was logged either way, so the
    feature was simply absent.

    Four things are asserted because each of them is one the raw-SMTP path could
    not do: the ROW's relay was dialled (the environment has no host at all),
    the message left as the row's identity, the survey THREADS onto the ticket's
    existing conversation, and the send is reported as `mail.sent` rather than
    being knowable only from a log.
    """
    await _enable_csat(db, project)
    db.add(
        MailSender(
            name=f"Desk {uuid.uuid4().hex[:6]}",
            kind=MailSenderKind.SMTP.value,
            is_default=True,
            from_address=DESK_FROM,
            reply_to=DESK_FROM,
            host="smtp.desk.test",
            port=2525,
            starttls=False,
        )
    )
    await db.flush()

    item = await _item(db, admin, project)
    await mail_service.upsert_contact(db, item.id, email="ext@example.com", name="Ext")
    inbound = f"<{uuid.uuid4().hex}@customer.example>"
    await mail_threading.record(
        db,
        message_id=inbound,
        item_id=item.id,
        direction=MailDirection.INBOUND,
        subject="Printer on fire",
    )
    event = await _resolve(db, admin, project, item.id)

    email = await sender.process_event(db, event)
    assert email is not None and email.item_id == item.id
    await sender._deliver(email, db)

    assert rows_only.dialled == [("smtp.desk.test", 2525)], "the ROW's relay, not the env"
    (message,) = rows_only.sent
    assert str(message["From"]) == DESK_FROM
    assert "ext@example.com" in str(message["To"])
    # `pin_subject`: its own sentence, not a `Re:` on the requester's subject…
    assert str(message["Subject"]) == f"[{item.key}] How did we do?"
    # …while the headers a client actually threads on still come from the store.
    assert str(message["In-Reply-To"]) == inbound
    assert inbound in str(message["References"])

    sent = await events_service.query_events(
        db, entity_id=str(item.id), event_types=[MailEvent.SENT.value]
    )
    assert len(sent) == 1
    assert sent[0].payload["recipients"] == ["ext@example.com"]
    # The survey's own outbound id is recorded, so a reply to it threads too.
    stored = await db.execute(
        select(MailMessage.direction).where(MailMessage.item_id == item.id)
    )
    assert sorted(stored.scalars()) == sorted(
        [MailDirection.INBOUND.value, MailDirection.OUTBOUND.value]
    )


# --- public flow ---


async def test_public_flow_latest_wins_responded_stamped_once(db, admin, project):
    item = await _item(db, admin, project)
    survey = await csat_service.create_survey(
        db, item_id=item.id, item_key=item.key
    )

    rendered = await csat_service.public_survey(db, survey.token)
    assert rendered.item_key == item.key and rendered.item_title == item.title
    assert rendered.rating is None and rendered.responded_at is None
    # Unanswered → the item-scoped read stays 404-quiet.
    with pytest.raises(NotFoundError):
        await csat_service.responded_survey(db, item.id)

    first = await csat_service.record_response(
        db, survey.token, PublicCsatSubmit(rating=4, comment="great")
    )
    assert first.rating == 4 and first.responded_at is not None
    stamped = first.responded_at

    # Re-submit: latest wins, the response stamp does NOT move.
    second = await csat_service.record_response(
        db, survey.token, PublicCsatSubmit(rating=2, comment="on reflection…")
    )
    assert second.rating == 2 and second.responded_at == stamped

    answered = await csat_service.responded_survey(db, item.id)
    assert answered.rating == 2 and answered.comment == "on reflection…"

    responded = await events_service.query_events(
        db,
        entity_type=ItemEntity.ITEM.value,
        entity_id=str(item.id),
        event_types=[CsatEvent.RESPONDED.value],
        ascending=True,
    )
    assert [e.payload["rating"] for e in responded] == [4, 2]
    assert all(e.actor_id is None for e in responded)


async def test_public_unknown_token_is_404(db):
    with pytest.raises(NotFoundError):
        await csat_service.public_survey(db, "not-a-real-token")
    with pytest.raises(NotFoundError):
        await csat_service.record_response(db, "not-a-real-token", PublicCsatSubmit(rating=5))


def test_public_submit_rating_bounds_and_comment_cap():
    for bad in (0, 6):
        with pytest.raises(ValidationError):
            PublicCsatSubmit(rating=bad)
    with pytest.raises(ValidationError):
        PublicCsatSubmit(rating=3, comment="x" * 2001)
    assert PublicCsatSubmit(rating=3, comment="x" * 2000).rating == 3


# --- report aggregation ---


async def test_sla_report_carries_csat_by_responded_week(db, admin, project):
    for rating in (5, 3):
        item = await _item(db, admin, project)
        survey = await csat_service.create_survey(
            db, item_id=item.id, item_key=item.key
        )
        await csat_service.record_response(db, survey.token, PublicCsatSubmit(rating=rating))

    buckets = (await reporting.sla_report(db, None, weeks=2)).buckets
    assert sum(b.csat_count for b in buckets) == 2
    week = next(b for b in buckets if b.csat_count)
    assert week.csat_avg == pytest.approx(4.0)
    # Weeks without responses stay None/0, and other projects see nothing.
    assert all(b.csat_avg is None for b in buckets if b.csat_count == 0)
    empty = (await reporting.sla_report(db, uuid.uuid4(), weeks=2)).buckets
    assert sum(b.csat_count for b in empty) == 0
