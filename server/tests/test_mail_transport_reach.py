"""Every sender rides the transport (RADD-983), and terminal failures are
visible (RADD-1036).

**The bug.** Three senders never got the RADD-958 treatment: the CSAT survey,
the notification DIGEST, and the `send_email` automation action all gated on
`settings.smtp_host` and delivered through `radd.smtp` off the environment. On
an instance configured entirely through Settings → Email — sender ROWS, no
`RADD_SMTP_*`, which is how radd-hq.com itself runs — each of them skipped, and
skipped SILENTLY: the guard returned, the cursor advanced, no line was logged.
They also skipped everything the transport had grown around them since:
threading, the per-source sender identity (RADD-979), `mail.sent`/`mail.failed`,
and the robot guard (RADD-996).

CSAT's leg is in `test_csat.py`, beside its other decision tests. This file
takes the two that had no home: the digest and the automation action, plus the
two properties that only exist once mail leaves through one seam —

* **loop safety.** `mail.sent` and `mail.failed` ARE automation triggers. The
  comment the engine's email branch used to carry said "nothing is emitted —
  inherently loop-safe", and routing the send through the transport ends that.
  What holds instead is `executor._one`'s `events.automated()` scope, and the
  test below is the one that says so out loud.
* **mail health.** A terminal delivery failure was two events in a stream
  nobody aggregated. `mail_health` is the seam Settings → Monitoring reads.
"""

import smtplib
import uuid
from datetime import timedelta
from email.message import EmailMessage

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd import smtp
from radd.clock import utcnow
from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole, UserSource
from radd.modules.automations import engine as automations_engine
from radd.modules.automations.planning import should_process
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.events import service as events_service
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.mailintake import service as mail_service, transport
from radd.modules.mailintake.models import MailSender
from radd.modules.mailintake.types import MailEvent, MailFailureReport, MailSenderKind
from radd.modules.monitoring import service as monitoring
from radd.modules.notify import emailer, service as notify_service
from radd.modules.notify.models import Notification
from radd.modules.notify.types import NotificationType
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

ROW_FROM = "desk@radd-hq.com"
ROW_HOST = "smtp.desk.test"
ROW_PORT = 2525


class _FakeSmtp:
    """Enough of smtplib.SMTP to capture what was composed and which relay was
    dialled. `fail` is the shape a refusal (a rate limit, an unknown recipient,
    a dead relay) has by the time it reaches this seam."""

    sent: list[EmailMessage] = []
    dialled: list[tuple] = []
    fail: bool = False

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
        if type(self).fail:
            raise smtplib.SMTPDataError(451, b"relay refused this message (test)")
        type(self).sent.append(message)


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
def rows_only(monkeypatch):
    """A captured socket and NO environment relay.

    `smtp_host` empty is the whole point: a message that goes out went out
    through a `mail_senders` row, so none of these assertions can be true by way
    of a fallback nobody configured.
    """
    _FakeSmtp.sent = []
    _FakeSmtp.dialled = []
    _FakeSmtp.fail = False
    monkeypatch.setattr(smtp.smtplib, "SMTP", _FakeSmtp)
    monkeypatch.setattr(settings, "smtp_host", "")
    return _FakeSmtp


@pytest.fixture
async def no_senders(db):
    """Disable every `mail_senders` row already committed to the test database —
    `default_sender` reads the table, not a fixture."""
    await db.execute(update(MailSender).values(enabled=False))


@pytest.fixture
async def sender_row(db, no_senders) -> MailSender:
    row = MailSender(
        name=f"Desk {uuid.uuid4().hex[:6]}",
        kind=MailSenderKind.SMTP.value,
        is_default=True,
        from_address=ROW_FROM,
        reply_to=ROW_FROM,
        host=ROW_HOST,
        port=ROW_PORT,
        starttls=False,
    )
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def world(db):
    suffix = uuid.uuid4().hex[:8]
    agent = User(
        email=f"ada-{suffix}@example.com",
        name="Ada Agent",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(agent)
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"MT{suffix[:4].upper()}", name="Mail transport")
    )
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Printer on fire"), agent
    )
    return agent, project, item


@pytest.fixture
async def quiet_backlog(db):
    """Stamp every notification already pending. `run_batch` selects GLOBALLY,
    exactly as the loop does, so a row another file committed would otherwise be
    mailed here — and could fill the batch and push this file's own rows out of
    it, producing a failure that depends on which tests ran first."""
    await db.execute(
        update(Notification).where(Notification.emailed_at.is_(None)).values(emailed_at=utcnow())
    )


async def _notify(db, user: User, item, type_: NotificationType, **payload) -> None:
    from radd.modules.auth import grants
    from radd.modules.auth.roles import role_by_key
    role = await role_by_key(db, "member")
    await grants.create_grant(db, role.id, user_id=user.id, project_id=item.project_id)
    await notify_service.create_notification(
        db,
        user_id=user.id,
        type_=type_,
        event_id=None,
        item_id=item.id,
        actor_id=None,
        payload={"item_key": "MT-1", "item_title": "Printer on fire", **payload},
    )
    await db.flush()


async def _person(db, name: str) -> User:
    user = User(
        email=f"{name.lower()}-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _mail_events(db, event_type: MailEvent):
    return await events_service.query_events(db, event_types=[event_type.value], limit=50)


# --- the digest ---------------------------------------------------------------


async def test_the_digest_sends_on_a_rows_only_instance(
    db, world, sender_row, rows_only, quiet_backlog
):
    """The digest had NEVER used a sender row — it dialled `radd.smtp` off the
    environment and gated on `settings.smtp_host`, so on a rows-only instance it
    returned 0 forever and stamped nothing.

    `state_changed` is deliberately not in `DEFAULT_EMAIL_TYPES`, so the row is
    the digest's by construction rather than by the per-event mailer having
    passed over it.
    """
    _agent, _project, item = world
    watcher = await _person(db, "Wanda")
    await _notify(
        db, watcher, item, NotificationType.STATE_CHANGED, **{"from": "Open", "to": "Done"}
    )

    assert await emailer.run_batch(db) == 1

    assert rows_only.dialled == [(ROW_HOST, ROW_PORT)], "the ROW's relay, not the env"
    (message,) = rows_only.sent
    assert str(message["From"]) == ROW_FROM
    assert watcher.email in str(message["To"])
    # A digest is about several items, so it threads onto none of them — the
    # itemless half of the transport, and the event says so.
    (sent,) = [
        event
        for event in await _mail_events(db, MailEvent.SENT)
        if event.payload.get("recipients") == [watcher.email]
    ]
    assert sent.payload.get("item") is None


async def test_a_digest_failure_is_an_event_and_not_an_exception(
    db, world, sender_row, rows_only, quiet_backlog
):
    """Two properties in one tick.

    The transport never raises, so one unreachable address costs the batch
    nothing — the loop keeps going and banks the failure on the row instead of
    unwinding out of `run_batch`. And the failure is now a `mail.failed` event,
    which is the only reason Settings → Monitoring can show it at all.
    """
    _agent, _project, item = world
    watcher = await _person(db, "Wanda")
    await _notify(
        db, watcher, item, NotificationType.STATE_CHANGED, **{"from": "Open", "to": "Done"}
    )
    rows_only.fail = True

    assert await emailer.run_batch(db) == 0

    (row,) = list(
        (
            await db.execute(
                Notification.__table__.select().where(Notification.user_id == watcher.id)
            )
        ).all()
    )
    assert row.emailed_at is None, "one relay blip must not lose the message"
    assert row.email_attempts == 1
    failures = [
        event
        for event in await _mail_events(db, MailEvent.FAILED)
        if event.payload.get("recipients") == [watcher.email]
    ]
    assert len(failures) == 1
    # The detail an operator needs: what the relay actually said.
    assert "451" in failures[0].payload["error"]
    assert failures[0].payload["given_up"] is False


# --- the send_email automation action -----------------------------------------


async def test_the_send_email_action_leaves_through_the_sender_row(
    db, sender_row, rows_only
):
    """`_apply_plan`'s EMAIL branch dialled `radd.smtp` directly, which made it
    the third sender a rows-only instance silently never sent from."""
    await automations_engine._send_email(
        db, "customer@example.com", "Cust Omer", "Your ticket", "We are on it."
    )

    assert rows_only.dialled == [(ROW_HOST, ROW_PORT)]
    (message,) = rows_only.sent
    assert str(message["From"]) == ROW_FROM
    assert str(message["Subject"]) == "Your ticket"
    assert "customer@example.com" in str(message["To"])


async def test_the_send_email_action_skip_logs_without_the_mail_module(
    db, sender_row, rows_only, monkeypatch, caplog
):
    """mailintake is optional and disableable. Absent, the action skips with a
    line rather than raising — the `contact` role's posture, and the opposite of
    the silence this whole issue is about."""
    monkeypatch.setattr(settings, "modules", tuple(
        m for m in settings.modules if m != "radd.modules.mailintake"
    ))

    with caplog.at_level("INFO"):
        await automations_engine._send_email(
            db, "customer@example.com", "Cust Omer", "Your ticket", "We are on it."
        )

    assert rows_only.sent == [] and rows_only.dialled == []
    assert any("mailintake module is not loaded" in record.message for record in caplog.records)


async def test_an_automations_own_mail_event_cannot_retrigger_it(db, sender_row, rows_only):
    """THE LOOP-SAFETY PROPERTY, stated where it can fail.

    `mail.sent` and `mail.failed` are declared triggers, so an automation that
    sends mail now emits an event its own rule could match — which is a spin,
    not a feature. What prevents it is `executor._one`: `_apply_plan` runs
    inside `with events.automated()`, so every event the send emits is marked
    automation-caused and `should_process` rejects it. The engine's email branch
    used to justify itself with "nothing is emitted — inherently loop-safe", and
    that sentence stopped being true the moment the send moved onto the
    transport.
    """
    from radd.modules.events import service as events

    before = await events_service.latest_event_id(db)
    with events.automated():
        await automations_engine._send_email(
            db, "customer@example.com", "", "Your ticket", "We are on it."
        )
    await db.flush()

    emitted = await events_service.read_after(db, before, 20)
    mail_events = [e for e in emitted if e.event_type == MailEvent.SENT.value]
    assert mail_events, "the send must still REPORT itself"
    for event in mail_events:
        assert event.automated is True
        assert not should_process(event), "an automation's own mail would retrigger it"

    # The control: the same event outside the scope is a perfectly good trigger,
    # so the guard is the scope and not the event type being unmatchable.
    await transport.send_plain_mail(
        db, to_address="human@example.com", subject="Hand-sent", text="hi"
    )
    await db.flush()
    human = [
        e
        for e in await events_service.read_after(db, before, 40)
        if e.event_type == MailEvent.SENT.value and e.payload.get("recipients") == ["human@example.com"]
    ]
    assert human and should_process(human[0])


# --- the robot guard reaches the roles ----------------------------------------


async def test_a_service_account_is_never_a_send_email_recipient(db, world):
    """`resolve_recipient` asked `user.active`, which a spec-113 SERVICE account
    passes. The rule now comes from `mailintake.service.mailable_user`, so CSAT
    and this action cannot disagree about who has a mailbox."""
    from radd.modules.automations.email_action import resolve_recipient

    _agent, project, _item = world
    robot = User(
        email=f"robot-{uuid.uuid4().hex[:8]}@service.radd.local",
        name="CI key",
        source=UserSource.SERVICE.value,
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(robot)
    await db.flush()
    created = await items_service.create_item(
        db,
        ItemCreate(project_id=project.id, title="Filed by a key", reporter_id=robot.id),
        (await db.get(User, SYSTEM_ACTOR_ID)) or robot,
    )
    await db.flush()
    # The ORM row: `resolve_recipient` reads `reporter_id`, which the read model
    # does not carry (it embeds a `reporter` ref instead).
    item = await items_service.require_item(db, created.id)

    assert await resolve_recipient(db, "reporter", item) is None
    # A literal address is untouched — the guard is about ACCOUNTS.
    assert await resolve_recipient(db, "someone@example.com", item) == (
        "someone@example.com",
        "",
    )


# --- mail health (RADD-1036) --------------------------------------------------


async def test_mail_health_is_quiet_until_something_fails(db, world, sender_row, rows_only):
    """A healthy instance reports zero — the card's resting state, and the
    assertion that stops "no failures" being indistinguishable from "the seam
    reads nothing at all"."""
    _agent, _project, item = world
    await transport.send_item_mail(
        db, item_id=item.id, to_address="ok@example.com", subject="[MT-1] hi", text="hi"
    )
    await db.flush()

    health = await mail_service.mail_health(db)
    assert health.failures == 0 and health.given_up == 0
    assert health.recent == () and health.capped is False


async def test_mail_health_reports_the_count_the_last_error_and_the_give_ups(
    db, world, sender_row, rows_only
):
    """The endpoint's whole contract, on the seam that computes it.

    A terminal failure has to be COUNTED SEPARATELY: "a relay blipped once and
    the retry worked" is not the same news as "four attempts failed and nobody
    is going to hear from us", and the ladder stamps the row either way, so the
    events are the only place the difference survives.
    """
    _agent, _project, item = world
    rows_only.fail = True

    await transport.send_item_mail(
        db, item_id=item.id, to_address="one@example.com", subject="[MT-1] hi", text="hi"
    )
    await transport.send_item_mail(
        db,
        item_id=item.id,
        to_address="two@example.com",
        subject="[MT-1] hi",
        text="hi",
        failure=MailFailureReport.TERMINAL,
    )
    # A retrying caller's middle attempt is deliberately NOT reported — the
    # incident that produced the ladder wrote one of these every five seconds.
    await transport.send_item_mail(
        db,
        item_id=item.id,
        to_address="three@example.com",
        subject="[MT-1] hi",
        text="hi",
        failure=MailFailureReport.SILENT,
    )
    await db.flush()

    health = await mail_service.mail_health(db)
    addressed = [failure for failure in health.recent if failure.recipient.endswith("example.com")]
    assert [failure.recipient for failure in addressed] == ["two@example.com", "one@example.com"]
    assert health.given_up == 1
    assert health.failures == 2, "the silent middle attempt must not be counted"
    assert "451" in addressed[0].error
    assert addressed[0].given_up is True

    # …and out through the page's own composition, which is what the router
    # serves. `available` is the mailintake-is-loaded answer, not a health one.
    card = await monitoring.mail_health(db)
    assert card.available is True
    assert card.failures == 2 and card.given_up == 1
    assert card.window_hours > 0
    assert "451" in card.recent[0].error


async def test_mail_health_ignores_failures_older_than_its_window(
    db, world, sender_row, rows_only
):
    """The question is "is mail working right now", so the window is the answer's
    scope — otherwise one bad afternoon leaves the card red for good."""
    _agent, _project, item = world
    rows_only.fail = True
    await transport.send_item_mail(
        db, item_id=item.id, to_address="old@example.com", subject="[MT-1] hi", text="hi"
    )
    await db.flush()
    assert (await mail_service.mail_health(db)).failures == 1

    stale = utcnow() - timedelta(hours=48)
    await db.execute(
        update(events_service.Event)
        .where(events_service.Event.event_type == MailEvent.FAILED.value)
        .values(created_at=stale)
    )
    assert (await mail_service.mail_health(db)).failures == 0


async def test_the_card_is_absent_rather_than_green_without_the_mail_module(
    db, monkeypatch
):
    """mailintake disabled is not a mail problem. `available=False` is what lets
    the page omit the card instead of claiming zero failures on an instance that
    cannot send at all — the ai-coverage precedent, one step further in."""
    monkeypatch.setattr(settings, "modules", tuple(
        m for m in settings.modules if m != "radd.modules.mailintake"
    ))
    card = await monitoring.mail_health(db)
    assert card.available is False and card.failures == 0
