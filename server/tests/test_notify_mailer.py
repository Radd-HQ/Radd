"""One fan-out: notify decides who hears, mailintake carries the mail (RADD-968).

There were two fan-outs and they disagreed. `mailintake.outbound` mailed
`notify.watcher_ids` minus the author on every public comment; the INBOX fanned
out over watchers ∪ participant-team members through `notify.consumer._allowed`
(item.read, the RADD-817 relation gate, the internal-comment filter, and since
RADD-971 the per-user mute). Four consequences, none of which raised anything:

- a participant-TEAM member got an inbox row and no email;
- a watcher who had since lost `item.read` still got the mail;
- muting `commented` silenced the bell and nothing else;
- and no event except `comment.created` ever produced an email at all.

The fix is that mail follows the ROWS. A notification row has already passed
every one of those gates, so mailing it needs no second copy of the policy —
which is exactly what drifted the first time. These tests therefore drive the
real consumer where the question is "who gets a row", and the real mailer tick
where it is "what goes in the mailbox".

RADD-686 then made WHICH rows mail a per-user answer rather than a constant
(`notification_prefs.email_types`), so the middle section drives several
recipients through one batch: a filter that had stayed global would still pass
every test written against a single user.

The delivery path is the real one end to end: `mailer.run_batch` →
`mailintake.service.send_item_mail` → `radd.smtp.send_message`, with only
`smtplib.SMTP` faked. That is deliberate — the reply-by-email test at the bottom
takes the Message-ID off the composed message and feeds it back through
`intake.accept`, which is only meaningful if the id it threads on is the one the
transport actually stored.
"""

import smtplib
import uuid
from datetime import timedelta
from email.message import EmailMessage

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd import smtp
from radd.config import settings
from radd.modules.auth import grants
from radd.modules.auth.models import User
from radd.modules.auth.roles import role_by_key
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole, UserSource
from radd.modules.comments import service as comments_service
from radd.modules.comments.schemas import CommentCreate
from radd.modules.comments.types import CommentVisibility
from radd.modules.events import service as events_service
from radd.modules.events.models import Event
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.mailintake import intake, parsing, threading as mail_threading
from radd.modules.mailintake.models import MailMessage, MailSender, MailSource
from radd.modules.mailintake.types import (
    MailDirection,
    MailEvent,
    MailSenderKind,
    MailSourceKind,
)
from radd.modules.notify import consumer, emailer, mailer, retry, service as notify_service
from radd.modules.notify.models import Notification
from radd.modules.notify.types import (
    CONSUMER_NAME,
    DEFAULT_EMAIL_TYPES,
    NotificationType,
)
from radd.modules.participants import service as participants
from radd.modules.participants.schemas import ParticipantAdd
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

BASE_URL = "https://radd.example.com"
RELAY_FROM = "agent@radd-hq.com"
RELAY_REPLY_TO = "help@radd-hq.com"
#: A SECOND identity, bound to one mail source (RADD-979). Distinct from the
#: default relay in both fields, so an assertion on either says which one
#: actually answered.
DESK_FROM = "support@radd-hq.com"


class _FakeSmtp:
    """Enough of smtplib.SMTP to capture every composed message.

    `dials` counts CONNECTIONS, not messages — that is the number RADD-996 and
    RADD-997 are both about. A recipient with no mailbox and a row inside its
    backoff must cost the relay nothing, and "no message was captured" cannot
    tell the difference between not connecting and connecting to say nothing.

    `fail` raises from the send, which is the shape a refusal (a rate limit, an
    unknown recipient, a dead relay) has by the time it reaches this seam.
    """

    sent: list[EmailMessage] = []
    dials: int = 0
    fail: bool = False

    def __init__(self, *args, **kwargs):
        type(self).dials += 1

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
            raise smtplib.SMTPException("relay refused this message (test)")
        type(self).sent.append(message)


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture(autouse=True)
def relay(monkeypatch):
    """A captured SMTP relay + a known base URL. Returns the sent list."""
    _FakeSmtp.sent = []
    _FakeSmtp.dials = 0
    _FakeSmtp.fail = False
    monkeypatch.setattr(smtp.smtplib, "SMTP", _FakeSmtp)
    monkeypatch.setattr(settings, "app_base_url", BASE_URL)
    return _FakeSmtp.sent


@pytest.fixture
def env_relay(monkeypatch):
    """The environment relay the DIGEST sends over (it has never used a sender
    row). Separate from `relay`, which fakes the socket for both channels."""
    monkeypatch.setattr(settings, "smtp_host", "smtp.env.test")
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_from_address", RELAY_FROM)


@pytest.fixture
async def quiet_backlog(db):
    """Stamp every notification already pending in the test database.

    `run_batch` selects GLOBALLY, exactly as the loop does. Without this, a row
    committed by some other test would be mailed here — and, worse, could fill
    the batch and push this test's own rows out of it, producing a failure that
    depends on which files ran first. Inside the test transaction, so it rolls
    back with everything else.
    """
    await db.execute(
        update(Notification)
        .where(Notification.emailed_at.is_(None))
        .values(emailed_at=mailer.utcnow())
    )


@pytest.fixture
async def no_senders(db):
    """Disable every `mail_senders` row already in the test database.

    `registry.default_sender` reads the table, not a fixture, so a row some
    other module committed (or `seed_from_env` wrote during an app-startup test)
    would decide this file's answers. Disabled inside the transaction, so it
    rolls back — and so "there is nowhere to send from" means it.
    """
    await db.execute(update(MailSender).values(enabled=False))


@pytest.fixture
async def sender_row(db, no_senders):
    """The `mail_senders` row outbound resolves — flushed, never committed."""
    row = MailSender(
        name=f"Relay {uuid.uuid4().hex[:6]}",
        kind=MailSenderKind.SMTP.value,
        is_default=True,
        from_address=RELAY_FROM,
        reply_to=RELAY_REPLY_TO,
        host="smtp.test",
        port=25,
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
        db, ProjectCreate(key=f"NM{suffix[:4].upper()}", name="Notify mailer")
    )
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Printer on fire"), agent
    )
    return agent, project, item


async def _user(db, *, name: str, email: str, active: bool = True) -> User:
    user = User(email=email, name=name, active=active, instance_role=InstanceRole.MEMBER.value)
    db.add(user)
    await db.flush()
    return user


async def _grant(db, user: User, key: BuiltinRoleKey, project_id: uuid.UUID) -> None:
    role = await role_by_key(db, key.value)
    await grants.create_grant(db, role.id, user_id=user.id, project_id=project_id)
    await db.flush()


async def _comment(db, item, author: User, body: str, *, internal: bool = False):
    """A real comment + its event, and the consumer's cursor parked just before
    it so the next `_consume` sees exactly this one."""
    head = await events_service.latest_event_id(db)
    await events_service.set_offset(db, CONSUMER_NAME, head)
    comment = await comments_service.create_comment(
        db,
        item.id,
        CommentCreate(
            body=body,
            visibility=(
                CommentVisibility.INTERNAL if internal else CommentVisibility.PUBLIC
            ),
        ),
        author,
    )
    await db.flush()
    return comment


async def _channels(
    db,
    user: User,
    *,
    email_types: list[NotificationType],
    muted_types: list[NotificationType] | None = None,
) -> None:
    """One user's channel matrix (RADD-686). Absence of a call means no row —
    which is itself a case worth testing, so it is never done implicitly."""
    await notify_service.set_prefs(
        db,
        user.id,
        muted_types=muted_types or [],
        email_types=email_types,
        email_digest=True,
    )


async def _notify(db, user: User, type_: NotificationType, item, **detail) -> None:
    """One notification row of `type_`, addressed at the world's item."""
    await notify_service.create_notification(
        db,
        user_id=user.id,
        type_=type_,
        event_id=None,  # nothing to resolve a comment through: the line stands alone
        item_id=item.id,
        actor_id=None,
        payload={
            "item_key": "NM-1",
            "item_title": "Printer on fire",
            "actor_name": "Ada Agent",
            **detail,
        },
    )


async def _share(db, item, actor: User, **subject) -> None:
    """A real participant add (RADD-978), consumed by the real consumer.

    The cursor is parked at the current head first, so the batch this reads is
    exactly the event the add emits.
    """
    head = await events_service.latest_event_id(db)
    await events_service.set_offset(db, CONSUMER_NAME, head)
    await participants.add_participant(db, item.id, ParticipantAdd(**subject), actor)
    await db.flush()
    await consumer._consume(db, watch_only=False)


async def _rows(db, user_id: uuid.UUID) -> list[Notification]:
    result = await db.execute(
        select(Notification).where(Notification.user_id == user_id)
    )
    return list(result.scalars())


def _to(message: EmailMessage) -> str:
    return str(message["To"])


def _addressed(sent: list[EmailMessage], email: str) -> list[EmailMessage]:
    return [m for m in sent if email in _to(m)]


def _text(message: EmailMessage) -> str:
    return message.get_body(("plain",)).get_content()


# --- the immediate email ------------------------------------------------------


async def test_a_notification_with_no_body_to_quote_still_gets_a_readable_email(
    db, world, relay, sender_row, quiet_backlog
):
    """A comment deleted between the fan-out and the five-second tick leaves a
    row with nothing to quote. It degrades to `mailrender.notice` — the digest's
    line on its own — rather than mailing an empty quote block. That is also the
    renderer every non-comment type uses now RADD-686 lets people ask for them.
    """
    _agent, project, item = world
    watcher = await _user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
    key = f"{project.key}-{item.number}"
    await notify_service.create_notification(
        db,
        user_id=watcher.id,
        type_=NotificationType.COMMENTED,
        event_id=None,  # nothing left to resolve the comment through
        item_id=item.id,
        actor_id=None,
        payload={"item_key": key, "item_title": "Printer on fire", "actor_name": "Ada Agent"},
    )

    assert await mailer.run_batch(db) == 1

    text = _text(_addressed(relay, watcher.email)[0])
    assert "Ada Agent commented" in text
    assert f"{BASE_URL}/issues/{key}" in text
    assert f"follow {key}" in text
    assert '""' not in text, "an empty quote block, where the comment used to be"


async def test_a_commented_notification_is_mailed_with_author_body_and_link(
    db, world, relay, sender_row, quiet_backlog
):
    """The message a watcher used to get from `mailintake.outbound`, now built
    from the notification row — and carrying the FULL comment rather than the
    200-char event excerpt."""
    agent, project, item = world
    watcher = await _user(db, name="Wanda Watcher", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
    body = ("We restarted it. " + "Detail. " * 60).strip()  # past the excerpt's 200-char cap
    await notify_service.add_watchers(db, item.id, [agent.id, watcher.id])
    await _grant(db, watcher, BuiltinRoleKey.MEMBER, project.id)
    await _comment(db, item, agent, body)
    await consumer._consume(db, watch_only=False)

    assert await mailer.run_batch(db) == 1

    message = _addressed(relay, watcher.email)[0]
    key = f"{project.key}-{item.number}"
    assert str(message["Subject"]) == f"[{key}] Printer on fire"
    assert str(message["Reply-To"]) == RELAY_REPLY_TO
    assert message.get_content_type() == "multipart/alternative"
    text = _text(message)
    assert "Ada Agent commented" in text
    assert body in text, "the excerpt was mailed instead of the comment"
    assert f"{BASE_URL}/issues/{key}" in text
    assert f"follow {key}" in text, "no reason line — the footer says why you got this"
    # The author is never mailed about their own comment.
    assert _addressed(relay, agent.email) == []


async def test_a_muted_type_never_becomes_a_row_and_so_never_becomes_mail(
    db, world, relay, sender_row, quiet_backlog
):
    """RADD-971 put the mute at the write; RADD-968 makes mail follow the write.
    The control user is the point: without one, "no mail" could equally mean the
    relay was never configured."""
    agent, project, item = world
    muted = await _user(db, name="Mo Muted", email=f"m-{uuid.uuid4().hex[:8]}@example.com")
    heard = await _user(db, name="Hana Heard", email=f"h-{uuid.uuid4().hex[:8]}@example.com")
    for user in (muted, heard):
        await notify_service.add_watchers(db, item.id, [user.id])
        await _grant(db, user, BuiltinRoleKey.MEMBER, project.id)
    # The stronger form since RADD-686: they ALSO asked for comment email. The
    # mute wins by construction — `set_prefs` normalises it out of email_types,
    # and there would be no row to mail either way.
    await notify_service.set_prefs(
        db,
        muted.id,
        muted_types=[NotificationType.COMMENTED],
        email_types=[NotificationType.COMMENTED],
        email_digest=True,
    )
    await _comment(db, item, agent, "Any update?")
    await consumer._consume(db, watch_only=False)

    await mailer.run_batch(db)

    assert await _rows(db, muted.id) == []
    assert _addressed(relay, muted.email) == []
    assert len(_addressed(relay, heard.email)) == 1


async def test_only_the_readers_of_an_internal_comment_are_mailed(
    db, world, relay, sender_row, quiet_backlog
):
    """New in RADD-968, and correct: internal comments now email exactly the
    users whose rows survived `comment.read_internal`. The external contact
    still never sees one — `outbound.should_reply`'s PUBLIC gate stands, and
    that leg no longer mails users at all."""
    agent, project, item = world
    insider = await _user(db, name="Ida Inside", email=f"i-{uuid.uuid4().hex[:8]}@example.com")
    outsider = await _user(db, name="Otto Outside", email=f"o-{uuid.uuid4().hex[:8]}@example.com")
    await notify_service.add_watchers(db, item.id, [insider.id, outsider.id])
    await _grant(db, insider, BuiltinRoleKey.MEMBER, project.id)  # comment.read_internal
    await _grant(db, outsider, BuiltinRoleKey.VIEWER, project.id)  # item.read only
    await _comment(db, item, agent, "Refund approved internally.", internal=True)
    await consumer._consume(db, watch_only=False)

    await mailer.run_batch(db)

    assert len(await _rows(db, insider.id)) == 1
    assert await _rows(db, outsider.id) == []
    assert len(_addressed(relay, insider.email)) == 1
    assert _addressed(relay, outsider.email) == []


# --- the per-user channel matrix (RADD-686) -----------------------------------


async def test_which_types_mail_immediately_is_each_recipients_own_answer(
    db, world, relay, sender_row, quiet_backlog
):
    """Three users, the same two notifications each, three outcomes — in ONE
    batch, which is the whole point. A global constant (RADD-968's
    `DEFAULT_IMMEDIATE_EMAIL_TYPES`) would have to give all three the same mail,
    and any single-user version of this test would pass against it.

    A keeps that old behaviour by asking for `commented` alone. B asked for
    everything, so the state change mails too — the first type other than
    `commented` ever to reach a mailbox individually. C asked for nothing
    immediate, and is the control that "no mail" is a preference rather than a
    broken relay.
    """
    _agent, _project, item = world
    only_comments = await _user(db, name="Ada", email=f"a-{uuid.uuid4().hex[:8]}@example.com")
    everything = await _user(db, name="Bo", email=f"b-{uuid.uuid4().hex[:8]}@example.com")
    inbox_only = await _user(db, name="Cyd", email=f"c-{uuid.uuid4().hex[:8]}@example.com")
    await _channels(db, only_comments, email_types=[NotificationType.COMMENTED])
    await _channels(db, everything, email_types=list(NotificationType))
    await _channels(db, inbox_only, email_types=[])
    for user in (only_comments, everything, inbox_only):
        await _notify(db, user, NotificationType.COMMENTED, item, excerpt="Any update?")
        await _notify(
            db, user, NotificationType.STATE_CHANGED, item, **{"from": "Open", "to": "Done"}
        )

    assert await mailer.run_batch(db) == 3  # 1 + 2 + 0

    for_a = [_text(message) for message in _addressed(relay, only_comments.email)]
    assert len(for_a) == 1 and "Ada Agent commented" in for_a[0]
    for_b = [_text(message) for message in _addressed(relay, everything.email)]
    assert len(for_b) == 2
    assert any("Ada Agent moved Open → Done" in text for text in for_b)
    assert _addressed(relay, inbox_only.email) == []
    # And what was not mailed is left UNSTAMPED: the digest is the other half of
    # the choice, not a fallback. Stamping here would silence it outright.
    unmailed = {
        user.id: sorted(row.type for row in await _rows(db, user.id) if row.emailed_at is None)
        for user in (only_comments, everything, inbox_only)
    }
    assert unmailed == {
        only_comments.id: [NotificationType.STATE_CHANGED.value],
        everything.id: [],
        inbox_only.id: [NotificationType.COMMENTED.value, NotificationType.STATE_CHANGED.value],
    }


async def test_inbox_only_still_reaches_the_mailbox_through_the_digest_once(
    db, world, relay, sender_row, quiet_backlog
):
    """`email_types: []` with the digest on is a real answer, not silence.

    The digest loop opens its own SessionLocal and so cannot see rows this
    transaction has not committed; what is asserted instead is its SELECTION
    (`emailed_at IS NULL`, verbatim) and its composition — which is where "once"
    lives: two rows in, two lines out, no duplicate of the one the mailer looked
    at and passed over.
    """
    _agent, _project, item = world
    inbox_only = await _user(db, name="Cyd", email=f"c-{uuid.uuid4().hex[:8]}@example.com")
    await _channels(db, inbox_only, email_types=[])
    await _notify(db, inbox_only, NotificationType.COMMENTED, item, excerpt="Any update?")
    await _notify(
        db, inbox_only, NotificationType.STATE_CHANGED, item, **{"from": "Open", "to": "Done"}
    )

    assert await mailer.run_batch(db) == 0
    assert relay == []

    result = await db.execute(
        select(Notification).where(
            Notification.emailed_at.is_(None), Notification.user_id == inbox_only.id
        )
    )
    pending = list(result.scalars())
    # Sorted, not ordered: `created_at` defaults to now(), which in Postgres is
    # the TRANSACTION timestamp — rows written together tie, and the id tiebreak
    # is a uuid4. Asserting a sequence here would flap.
    assert sorted(row.type for row in pending) == sorted(
        [NotificationType.COMMENTED.value, NotificationType.STATE_CHANGED.value]
    )
    digest = emailer.compose(pending, {})
    assert digest.text.count("Ada Agent commented") == 1
    assert digest.text.count("Ada Agent moved Open → Done") == 1


async def test_a_user_who_never_saved_a_preference_gets_the_default_set(
    db, world, relay, sender_row, quiet_backlog
):
    """No prefs row = `DEFAULT_EMAIL_TYPES`, the personally-directed four.

    So a mention now mails as it happens — under RADD-968's constant only
    `commented` ever did — while a state change on something they merely watch
    still waits for the digest. Both halves are asserted, because widening the
    default is only right if it stopped somewhere.
    """
    _agent, _project, item = world
    assert NotificationType.MENTIONED in DEFAULT_EMAIL_TYPES
    assert NotificationType.STATE_CHANGED not in DEFAULT_EMAIL_TYPES
    newcomer = await _user(db, name="Nia", email=f"n-{uuid.uuid4().hex[:8]}@example.com")
    assert await notify_service.get_prefs(db, newcomer.id) is None, "the absence IS the fixture"
    await _notify(db, newcomer, NotificationType.MENTIONED, item, source="comment")
    await _notify(
        db, newcomer, NotificationType.STATE_CHANGED, item, **{"from": "Open", "to": "Done"}
    )

    assert await mailer.run_batch(db) == 1

    (message,) = _addressed(relay, newcomer.email)
    assert "Ada Agent mentioned you in the comment" in _text(message)
    unmailed = [row.type for row in await _rows(db, newcomer.id) if row.emailed_at is None]
    assert unmailed == [NotificationType.STATE_CHANGED.value]


async def test_being_shared_into_an_issue_mails_the_person_it_reaches(
    db, world, relay, sender_row, quiet_backlog
):
    """RADD-978, end to end: the real add, the real consumer, the real tick.

    `participant_added` is personally directed, so it joins `DEFAULT_EMAIL_TYPES`
    — someone shared into an issue hears about it now, not in tomorrow's digest,
    which is the whole point of telling them at all. The recipient holds nothing
    on the project: they pass the consumer's read gate through the Baseline's
    `item.read@participant`, i.e. through the row being announced.
    """
    agent, project, item = world
    colleague = await _user(db, name="Colleague", email=f"p-{uuid.uuid4().hex[:8]}@example.com")
    assert await notify_service.get_prefs(db, colleague.id) is None, "the absence IS the fixture"
    assert NotificationType.PARTICIPANT_ADDED in DEFAULT_EMAIL_TYPES

    await _share(db, item, agent, user_id=colleague.id)

    assert await mailer.run_batch(db) == 1

    key = f"{project.key}-{item.number}"
    (message,) = _addressed(relay, colleague.email)
    assert str(message["Subject"]) == f"[{key}] Printer on fire"
    text = _text(message)
    assert "Ada Agent added you to the issue" in text, "the line must name who shared it"
    assert f"{BASE_URL}/issues/{key}" in text, "and link the issue they can now open"


async def test_a_preference_saved_before_the_type_existed_does_not_mail_it(
    db, world, relay, sender_row, quiet_backlog
):
    """The asymmetry RADD-978 accepted, asserted rather than assumed.

    `d686emailtypes` backfilled every existing preferences row with the four
    types that were default THEN, and no migration adds this one — rewriting a
    stored preference to switch on a channel the person never asked for is worse
    than the inconsistency. So an explicit row from that backfill gets the inbox
    row and no mail, while the newcomer above gets both. The row is left
    UNSTAMPED, so the digest still carries it: this is a channel choice, not
    silence.
    """
    agent, _project, item = world
    settled = await _user(db, name="Settled", email=f"s-{uuid.uuid4().hex[:8]}@example.com")
    # Verbatim what the migration wrote, not `default_email_types()` — the point
    # is a row that predates the type.
    await _channels(
        db,
        settled,
        email_types=[
            NotificationType.ASSIGNED,
            NotificationType.MENTIONED,
            NotificationType.COMMENTED,
            NotificationType.APPROVAL,
        ],
    )

    await _share(db, item, agent, user_id=settled.id)

    assert await mailer.run_batch(db) == 0
    assert _addressed(relay, settled.email) == []
    (row,) = await _rows(db, settled.id)
    assert row.type == NotificationType.PARTICIPANT_ADDED.value
    assert row.emailed_at is None, "the digest can no longer see it"


async def test_a_type_mailed_from_a_non_comment_event_does_not_crash_the_tick(
    db, world, relay, sender_row, quiet_backlog
):
    """The bug RADD-978 surfaced, asserted in the type it was always reachable
    from rather than only in the new one.

    `mailer._comment_id` resolved the notification's event blindly, and an ITEM
    event's `entity_id` is the item — so the transport was handed an item uuid as
    a comment id and the tick died on a foreign-key violation. `assigned` is in
    `DEFAULT_EMAIL_TYPES`, so this was one assignment away on every instance with
    mailintake configured. It never fired in this file because every non-comment
    case here was written with `event_id=None`, which is the one shape that
    cannot reach the lookup.
    """
    agent, project, item = world
    assignee = await _user(db, name="Ash Assignee", email=f"as-{uuid.uuid4().hex[:8]}@example.com")
    await _grant(db, assignee, BuiltinRoleKey.MEMBER, project.id)
    head = await events_service.latest_event_id(db)
    await events_service.set_offset(db, CONSUMER_NAME, head)
    await items_service.update_item(db, item.id, ItemUpdate(assignee_id=assignee.id), agent)
    await db.flush()
    await consumer._consume(db, watch_only=False)

    assert await mailer.run_batch(db) == 1

    (message,) = _addressed(relay, assignee.email)
    assert "Ada Agent assigned you" in _text(message)
    # Threaded on the ITEM with no comment attached — which is what the transport
    # has to be told, rather than being handed the item's id as one.
    stored = await db.execute(
        select(MailMessage.comment_id).where(MailMessage.item_id == item.id)
    )
    assert list(stored.scalars()) == [None]


async def test_an_item_update_reaches_its_assignee_and_the_people_it_mentions(
    db, world, relay, sender_row, quiet_backlog
):
    """The row half of the same find, and the more serious one.

    RADD-922 nested the item event payload under `item`; `_handle_item_event`
    went on reading a top-level `project_id` and a top-level `description`. The
    first raised KeyError inside the consumer's per-event SAVEPOINT — logged,
    skipped, cursor advanced — so `assigned`, `state_changed` and description
    `mentioned` produced nothing for anyone; the second silently mention-scanned
    an empty string. No test drove this handler over a REAL item event, which is
    the only reason a dead third of the notification types looked healthy.
    """
    agent, project, item = world
    assignee = await _user(db, name="Ash", email=f"ash-{uuid.uuid4().hex[:8]}@example.com")
    named = await _user(db, name="Nina Named", email=f"n-{uuid.uuid4().hex[:8]}@example.com")
    for user in (assignee, named):
        await _grant(db, user, BuiltinRoleKey.MEMBER, project.id)
    head = await events_service.latest_event_id(db)
    await events_service.set_offset(db, CONSUMER_NAME, head)

    await items_service.update_item(
        db,
        item.id,
        ItemUpdate(
            assignee_id=assignee.id,
            description=f"Handing over — @[Nina Named]({named.id}) has the runbook.",
        ),
        agent,
    )
    await db.flush()
    await consumer._consume(db, watch_only=False)

    assert [row.type for row in await _rows(db, assignee.id)] == [
        NotificationType.ASSIGNED.value
    ]
    assert [row.type for row in await _rows(db, named.id)] == [
        NotificationType.MENTIONED.value
    ]


# --- the two channels' hand-off ----------------------------------------------


async def test_a_mailed_row_is_stamped_so_the_digest_never_repeats_it(
    db, world, relay, sender_row, quiet_backlog
):
    """The dedup between the two channels is `emailed_at`, which the digest's
    selection already filters on — no new column, no new query."""
    agent, project, item = world
    watcher = await _user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
    await notify_service.add_watchers(db, item.id, [watcher.id])
    await _grant(db, watcher, BuiltinRoleKey.MEMBER, project.id)
    await _comment(db, item, agent, "Engineer dispatched.")
    await consumer._consume(db, watch_only=False)

    await mailer.run_batch(db)

    (row,) = await _rows(db, watcher.id)
    assert row.emailed_at is not None
    # The digest's own predicate, verbatim.
    pending = await db.execute(
        select(Notification.id).where(
            Notification.emailed_at.is_(None), Notification.user_id == watcher.id
        )
    )
    assert list(pending.scalars()) == []
    # And a second tick does not send it again.
    before = len(relay)
    assert await mailer.run_batch(db) == 0
    assert len(relay) == before


async def test_a_type_the_recipient_did_not_ask_for_is_left_for_the_digest(
    db, world, relay, sender_row, quiet_backlog
):
    """A row the mailer skips must keep its `emailed_at` NULL, or the digest —
    whose selection is exactly that — would never see it either and the
    notification would reach nobody at all. The two channels are a partition."""
    _agent, _project, item = world
    watcher = await _user(db, name="Ava", email=f"a-{uuid.uuid4().hex[:8]}@example.com")
    await _channels(db, watcher, email_types=[NotificationType.COMMENTED])
    await _notify(db, watcher, NotificationType.STATE_CHANGED, item, **{"from": "Open", "to": "Done"})

    assert await mailer.run_batch(db) == 0

    (row,) = await _rows(db, watcher.id)
    assert row.emailed_at is None, "the digest can no longer see it"
    assert _addressed(relay, watcher.email) == []


async def test_a_recipient_with_no_mailbox_is_stamped_rather_than_retried_forever(
    db, world, relay, sender_row, quiet_backlog
):
    """Inactive or addressless is a PERMANENT skip, not a delivery failure —
    stamping it is what stops a 5-second loop reconsidering it all day."""
    _agent, _project, item = world
    departed = await _user(
        db, name="Gone", email=f"g-{uuid.uuid4().hex[:8]}@example.com", active=False
    )
    addressless = await _user(db, name="No Mail", email="")
    for user in (departed, addressless):
        await notify_service.create_notification(
            db,
            user_id=user.id,
            type_=NotificationType.COMMENTED,
            event_id=None,
            item_id=item.id,
            actor_id=None,
            payload={"item_key": "NM-1", "item_title": "Printer on fire", "excerpt": "hi"},
        )

    assert await mailer.run_batch(db) == 0

    for user in (departed, addressless):
        (row,) = await _rows(db, user.id)
        assert row.emailed_at is not None
    assert relay == []


# --- accounts that are not mailboxes (RADD-996) -------------------------------


async def _service_account(db) -> User:
    """A spec-113 service account, exactly as `create_service_account` makes one:
    `UserSource.SERVICE`, an address at a domain that does not receive."""
    user = User(
        email=f"agent-{uuid.uuid4().hex[:8]}@service.radd.local",
        name="CI agent",
        instance_role=InstanceRole.MEMBER.value,
        source=UserSource.SERVICE.value,
    )
    db.add(user)
    await db.flush()
    return user


async def test_a_service_account_is_stamped_without_the_relay_being_dialled(
    db, world, relay, sender_row, quiet_backlog
):
    """RADD-996: `radd-agent@service.radd.local` is not a mailbox.

    Service accounts have been receiving notification mail since v0.29.0, and
    the live incident is what it costs — the relay was rate-limited partly for
    repeatedly posting to addresses that bounce. The skip is PERMANENT, so the
    row is stamped like the inactive/address-less case: retrying can only
    produce the same answer more slowly.

    `dials` rather than `sent` is the assertion, because a message that is never
    composed still costs a connection if the loop reaches the relay at all.
    """
    _agent, _project, item = world
    robot = await _service_account(db)
    await _notify(db, robot, NotificationType.COMMENTED, item, excerpt="Any update?")

    assert await mailer.run_batch(db) == 0

    assert _FakeSmtp.dials == 0, "the relay was dialled for an address that does not receive"
    (row,) = await _rows(db, robot.id)
    assert row.emailed_at is not None, "unstamped means the digest tries the same address"
    # The control: the same batch, one line later, with a person on it.
    human = await _user(db, name="Hana", email=f"h-{uuid.uuid4().hex[:8]}@example.com")
    await _notify(db, human, NotificationType.COMMENTED, item, excerpt="Any update?")
    assert await mailer.run_batch(db) == 1
    assert _FakeSmtp.dials == 1


async def test_the_digest_skips_a_service_account_and_stamps_it(
    db, world, relay, env_relay, quiet_backlog
):
    """The other loop, which had the same bug and no end-to-end test at all.

    `state_changed` is deliberately not in `DEFAULT_EMAIL_TYPES`, so these rows
    are the digest's by construction rather than by the mailer having passed
    over them.
    """
    _agent, _project, item = world
    robot = await _service_account(db)
    human = await _user(db, name="Hana", email=f"h-{uuid.uuid4().hex[:8]}@example.com")
    for user in (robot, human):
        await _notify(
            db, user, NotificationType.STATE_CHANGED, item, **{"from": "Open", "to": "Done"}
        )

    assert await emailer.run_batch(db) == 1

    assert _addressed(relay, robot.email) == []
    assert len(_addressed(relay, human.email)) == 1
    for user in (robot, human):
        (row,) = await _rows(db, user.id)
        assert row.emailed_at is not None, "the backlog must drain either way"


# --- delivery failures back off (RADD-997) ------------------------------------


async def _failures(db, item_id: uuid.UUID) -> list[Event]:
    result = await db.execute(
        select(Event).where(
            Event.event_type == MailEvent.FAILED.value, Event.entity_id == str(item_id)
        )
    )
    return list(result.scalars())


async def test_a_failed_send_waits_out_a_delay_instead_of_retrying_every_tick(
    db, world, relay, sender_row, quiet_backlog
):
    """The incident, in one row (RADD-997).

    A failure left the row exactly as `_pending` had found it, so the 5-second
    mailer selected it again on the next tick, and the next, for the whole
    24-hour age window: an SMTP connection and a `mail.failed` event per
    recipient per five seconds. The row now carries its own backoff, and the
    second tick is the assertion that matters — the relay is not dialled at all.
    """
    _agent, _project, item = world
    watcher = await _user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
    await _notify(db, watcher, NotificationType.COMMENTED, item, excerpt="Any update?")
    _FakeSmtp.fail = True

    assert await mailer.run_batch(db) == 0

    (row,) = await _rows(db, watcher.id)
    assert row.emailed_at is None, "one relay blip must not lose the message"
    assert row.email_attempts == 1
    assert row.email_next_try is not None
    assert row.email_next_try - mailer.utcnow() <= retry.EMAIL_RETRY_DELAYS[0]
    dialled = _FakeSmtp.dials

    assert await mailer.run_batch(db) == 0
    assert _FakeSmtp.dials == dialled, "the row was reconsidered inside its own backoff"

    # The delay passes and the relay recovers: the message goes, once.
    _FakeSmtp.fail = False
    row.email_next_try = mailer.utcnow() - timedelta(seconds=1)
    await db.flush()

    assert await mailer.run_batch(db) == 1

    assert len(_addressed(relay, watcher.email)) == 1
    assert row.emailed_at is not None
    assert row.email_attempts == 1, "a success does not rewrite what happened before it"


async def test_the_ladder_ends_in_a_stamp_and_exactly_two_failure_events(
    db, world, relay, sender_row, quiet_backlog
):
    """Giving up, and the event half of the same fix.

    The stamp is the terminal state because the digest's selection is
    `emailed_at IS NULL` — leaving the row unstamped would hand an address that
    has refused four times straight to the other loop. And `mail.failed` is
    emitted on the FIRST failure and the LAST one only: the event is item-scoped
    and drives automations and the activity feed, so it answers "did this person
    hear from us", which the retries in between do not re-answer.
    """
    _agent, _project, item = world
    watcher = await _user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
    await _notify(db, watcher, NotificationType.COMMENTED, item, excerpt="Any update?")
    _FakeSmtp.fail = True

    row = None
    for attempt in range(len(retry.EMAIL_RETRY_DELAYS) + 1):
        assert await mailer.run_batch(db) == 0
        (row,) = await _rows(db, watcher.id)
        assert row.email_attempts == attempt + 1
        if row.emailed_at is None:
            row.email_next_try = mailer.utcnow() - timedelta(seconds=1)
            await db.flush()

    assert row.emailed_at is not None, "the ladder must end, or the row lives for a day"
    assert row.email_attempts == len(retry.EMAIL_RETRY_DELAYS) + 1
    assert len(await _failures(db, item.id)) == 2

    # Nothing looks at the row again — not this loop…
    dialled = _FakeSmtp.dials
    assert await mailer.run_batch(db) == 0
    assert _FakeSmtp.dials == dialled
    # …and not the digest, whose selection is exactly the stamp.
    pending = await db.execute(
        select(Notification.id).where(
            Notification.emailed_at.is_(None), Notification.user_id == watcher.id
        )
    )
    assert list(pending.scalars()) == []


async def test_a_failed_digest_takes_the_same_ladder(
    db, world, relay, env_relay, quiet_backlog
):
    """The digest's retry was gentler (300s, one message per user rather than
    one per row) and equally unbounded. Same columns, same ladder, same terminal
    stamp — written once in `retry.py` so the two loops cannot drift apart."""
    _agent, _project, item = world
    watcher = await _user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
    await _notify(
        db, watcher, NotificationType.STATE_CHANGED, item, **{"from": "Open", "to": "Done"}
    )
    _FakeSmtp.fail = True

    assert await emailer.run_batch(db) == 0

    (row,) = await _rows(db, watcher.id)
    assert row.emailed_at is None
    assert row.email_attempts == 1
    assert row.email_next_try is not None
    dialled = _FakeSmtp.dials
    assert await emailer.run_batch(db) == 0
    assert _FakeSmtp.dials == dialled

    for _ in range(len(retry.EMAIL_RETRY_DELAYS)):
        row.email_next_try = mailer.utcnow() - timedelta(seconds=1)
        await db.flush()
        assert await emailer.run_batch(db) == 0

    assert row.emailed_at is not None, "an address that refuses forever is given up on"


# --- transport ----------------------------------------------------------------


async def test_without_mailintake_the_env_relay_still_sends(
    db, world, relay, quiet_backlog, monkeypatch
):
    """mailintake is optional and disableable. Absent, the message still goes —
    over the env relay, the digest's existing posture. What is lost is the
    conversation: no thread row, so a reply opens a new ticket."""
    _agent, _project, item = world
    monkeypatch.setattr(mailer, "_mail_transport", lambda: None)
    monkeypatch.setattr(settings, "smtp_host", "smtp.env.test")
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_from_address", RELAY_FROM)
    watcher = await _user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
    await notify_service.create_notification(
        db,
        user_id=watcher.id,
        type_=NotificationType.COMMENTED,
        event_id=None,
        item_id=item.id,
        actor_id=None,
        payload={"item_key": "NM-1", "item_title": "Printer on fire", "excerpt": "any update?"},
    )

    assert await mailer.run_batch(db) == 1

    assert len(_addressed(relay, watcher.email)) == 1
    stored = await db.execute(select(MailMessage).where(MailMessage.item_id == item.id))
    assert list(stored.scalars()) == []


async def test_nothing_is_stamped_when_there_is_nowhere_to_send_from(
    db, world, relay, quiet_backlog, no_senders, monkeypatch
):
    """No sender row and no env relay: the rows stay pending. Stamping them
    would silently drop the notification email of every instance that has not
    configured SMTP yet."""
    _agent, _project, item = world
    monkeypatch.setattr(settings, "smtp_host", "")
    watcher = await _user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
    await notify_service.create_notification(
        db,
        user_id=watcher.id,
        type_=NotificationType.COMMENTED,
        event_id=None,
        item_id=item.id,
        actor_id=None,
        payload={"item_key": "NM-1", "item_title": "Printer on fire"},
    )

    assert await mailer.run_batch(db) == 0

    (row,) = await _rows(db, watcher.id)
    assert row.emailed_at is None
    assert relay == []


async def test_a_reply_to_a_notification_email_threads_back_onto_the_issue(
    db, world, relay, sender_row, quiet_backlog
):
    """The whole point of routing notification mail through mailintake.

    A notification email now carries the sender's Reply-To and its Message-ID is
    recorded against the item, so an internal user who simply hits Reply lands
    on the issue as a comment instead of opening a duplicate ticket.
    """
    agent, project, item = world
    watcher = await _user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
    await notify_service.add_watchers(db, item.id, [watcher.id])
    await _grant(db, watcher, BuiltinRoleKey.MEMBER, project.id)
    await _comment(db, item, agent, "Engineer dispatched.")
    await consumer._consume(db, watch_only=False)
    await mailer.run_batch(db)

    outbound_id = str(_addressed(relay, watcher.email)[0]["Message-ID"])
    # Recorded against the item — the id the RELAY used, not one we assumed.
    stored = await db.execute(
        select(MailMessage.message_id).where(MailMessage.item_id == item.id)
    )
    assert outbound_id in set(stored.scalars())

    incoming = EmailMessage()
    incoming["Subject"] = "Re: a subject their client rewrote"  # no key to fall back on
    incoming["From"] = f"Wanda <{watcher.email}>"
    incoming["To"] = RELAY_REPLY_TO
    incoming["Message-ID"] = "<reply-from-wanda@example.com>"
    incoming["In-Reply-To"] = outbound_id
    incoming.set_content("Confirmed fixed, thanks.")
    raw = incoming.as_bytes()

    outcome = await intake.accept(
        db,
        parsing.parse_email(raw),
        raw=raw,
        default_project_key=project.key,
        own_addresses={RELAY_FROM},
    )

    assert outcome.result is intake.Result.APPENDED
    assert outcome.item_id == item.id


async def test_the_subject_opens_the_thread_and_then_follows_it(
    db, world, relay, sender_row, quiet_backlog
):
    """First message out: `[KEY] Title`. Every later one: the STORED subject
    with one `Re: `, so renaming the issue cannot split the conversation."""
    agent, project, item = world
    watcher = await _user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
    await notify_service.add_watchers(db, item.id, [watcher.id])
    await _grant(db, watcher, BuiltinRoleKey.MEMBER, project.id)
    key = f"{project.key}-{item.number}"

    await _comment(db, item, agent, "First reply.")
    await consumer._consume(db, watch_only=False)
    await mailer.run_batch(db)

    item.title = "Printer no longer on fire"
    await db.flush()
    await _comment(db, item, agent, "Second reply.")
    await consumer._consume(db, watch_only=False)
    await mailer.run_batch(db)

    subjects = [str(m["Subject"]) for m in _addressed(relay, watcher.email)]
    assert subjects == [f"[{key}] Printer on fire", f"Re: [{key}] Printer on fire"]


async def test_notification_mail_leaves_from_the_source_the_ticket_arrived_at(
    db, world, relay, no_senders, quiet_backlog
):
    """RADD-979's third leg — and the one that shows the resolution point is
    SHARED rather than copied.

    Notify knows nothing about mail sources: it hands the transport an item and
    a recipient and is done. A ticket that arrived at the support desk is
    nonetheless mailed to its watchers AS the desk, because which identity
    answers is decided once, inside `transport._sender`, and every caller rides
    it. Had the lookup been added at the reply consumer instead, this leg would
    have kept signing as the instance default with nothing anywhere saying so —
    which is the same shape of bug as the two fan-outs RADD-968 merged.
    """
    agent, project, item = world
    house = MailSender(
        name=f"House {uuid.uuid4().hex[:6]}",
        kind=MailSenderKind.SMTP.value,
        is_default=True,
        from_address=RELAY_FROM,
        reply_to=RELAY_REPLY_TO,
        host="smtp.house.test",
        port=25,
        starttls=False,
    )
    desk = MailSender(
        name=f"Desk {uuid.uuid4().hex[:6]}",
        kind=MailSenderKind.SMTP.value,
        from_address=DESK_FROM,
        reply_to=DESK_FROM,
        host="smtp.desk.test",
        port=25,
        starttls=False,
    )
    db.add_all([house, desk])
    await db.flush()
    source = MailSource(
        name=f"Support {uuid.uuid4().hex[:6]}",
        kind=MailSourceKind.IMAP.value,
        address=DESK_FROM,
        host="imap.test",
        username=DESK_FROM,
        secret="pw",
        sender_id=desk.id,
    )
    db.add(source)
    await db.flush()
    # The item's mail ORIGIN. Recorded directly here because what is under test
    # is the lookup, not intake's passing of the source — `test_mail_config.py`
    # drives that half through `intake.accept`.
    await mail_threading.record(
        db,
        message_id=f"<{uuid.uuid4().hex}@customer.example>",
        item_id=item.id,
        direction=MailDirection.INBOUND,
        subject="Printer on fire",
        source_id=source.id,
    )

    watcher = await _user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
    await notify_service.add_watchers(db, item.id, [watcher.id])
    await _grant(db, watcher, BuiltinRoleKey.MEMBER, project.id)
    await _comment(db, item, agent, "Engineer dispatched.")
    await consumer._consume(db, watch_only=False)

    assert await mailer.run_batch(db) == 1

    message = _addressed(relay, watcher.email)[0]
    assert str(message["From"]) == DESK_FROM
    assert str(message["Reply-To"]) == DESK_FROM
    # The default relay exists, is enabled and is marked — it simply is not the
    # one that answers for this conversation.
    assert house.is_default is True
