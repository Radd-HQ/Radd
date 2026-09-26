"""Mail follows the notification ROWS (RADD-968): notify decides who hears,
mailintake carries it, so the mailer needs no second copy of the permission,
team and mute policy. Tests drive the real consumer for "who gets a row" and the
real `mailer.run_batch` → `send_item_mail` → `radd.smtp` path for "what reaches a
mailbox", faking only `smtplib.SMTP` — the reply-by-email test feeds the stored
Message-ID back through `intake.accept`. Which rows mail is per recipient
(RADD-686), so those tests put several recipients through ONE batch.
"""

import smtplib
import uuid
from datetime import timedelta
from email.message import EmailMessage

import pytest
from sqlalchemy import select, update

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
from radd.modules.notify import consumer, emailer, mailer, retry, rules as notify_rules
from radd.modules.notify import service as notify_service
from radd.modules.notify.kinds import every_kind
from radd.modules.notify.models import Notification
from radd.modules.notify.types import (
    CONSUMER_NAME,
    RELATIONSHIP_SCOPES,
    Channel,
    NotificationType,
)
from radd.modules.participants import service as participants
from radd.modules.participants.schemas import ParticipantAdd
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

from _factories import make_user

BASE_URL = "https://radd.example.com"
RELAY_FROM = "agent@radd-hq.com"
RELAY_REPLY_TO = "help@radd-hq.com"
#: A SECOND identity, bound to one mail source (RADD-979). Distinct from the
#: default relay in both fields, so an assertion on either says which one
#: actually answered.
DESK_FROM = "support@radd-hq.com"


class _FakeSmtp:
    """Enough of smtplib.SMTP to capture every composed message. `dials` counts
    CONNECTIONS: "no message captured" cannot tell not connecting from connecting to
    say nothing (RADD-996/997). `fail` raises from the send, as a refusal would."""

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
    """Stamp every pending notification: `run_batch` selects GLOBALLY, so another
    test's committed row could be mailed here or push this test's rows out of the
    batch. Inside the transaction, so it rolls back."""
    await db.execute(
        update(Notification)
        .where(Notification.emailed_at.is_(None))
        .values(emailed_at=mailer.utcnow())
    )


@pytest.fixture
async def no_senders(db):
    """Disable every `mail_senders` row: `registry.default_sender` reads the table,
    so a row another module committed would decide this file's answers. Rolls back
    with the transaction, so "nowhere to send from" means it."""
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
    """One user's RADD-686 "which types are mailed" answer, written into all three
    relationship columns the way the migration converts a stored preference (muted →
    `off`, emailed → `both`, else `inbox`). No call = no rule rows, never implicit."""
    muted = set(muted_types or [])
    emailed = set(email_types)
    channels = {
        str(kind): (
            Channel.OFF.value
            if kind in muted
            else Channel.BOTH.value
            if kind in emailed
            else Channel.INBOX.value
        )
        for kind in every_kind()
    }
    await notify_service.set_rules(
        db, user.id, [(scope, None, channels) for scope in RELATIONSHIP_SCOPES]
    )


async def _notify(db, user: User, type_: NotificationType, item, **detail) -> None:
    """One eligible notification row, addressed at the world's item."""
    if not await db.scalar(select(grants.GlobalRoleGrant.id).where(
        grants.GlobalRoleGrant.user_id == user.id,
        grants.GlobalRoleGrant.project_id == item.project_id,
    )):
        await _grant(db, user, BuiltinRoleKey.MEMBER, item.project_id)
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
    watcher = await make_user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
    key = f"{project.key}-{item.number}"
    await _grant(db, watcher, BuiltinRoleKey.MEMBER, project.id)
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
    watcher = await make_user(
        db, name="Wanda Watcher", email=f"w-{uuid.uuid4().hex[:8]}@example.com"
    )
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
    muted = await make_user(db, name="Mo Muted", email=f"m-{uuid.uuid4().hex[:8]}@example.com")
    heard = await make_user(db, name="Hana Heard", email=f"h-{uuid.uuid4().hex[:8]}@example.com")
    for user in (muted, heard):
        await notify_service.add_watchers(db, item.id, [user.id])
        await _grant(db, user, BuiltinRoleKey.MEMBER, project.id)
    # The stronger form since RADD-686: they ALSO asked for comment email. `off`
    # wins because it is the SAME cell — spec 118 made the two channels
    # independent, but the third state is still one answer per (scope, kind), so
    # there is no contradiction left to normalise away.
    await _channels(
        db,
        muted,
        muted_types=[NotificationType.COMMENTED],
        email_types=[NotificationType.COMMENTED],
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
    insider = await make_user(db, name="Ida Inside", email=f"i-{uuid.uuid4().hex[:8]}@example.com")
    outsider = await make_user(
        db, name="Otto Outside", email=f"o-{uuid.uuid4().hex[:8]}@example.com"
    )
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
    """Three users, the same two notifications, three outcomes in ONE batch — a
    global constant would give all three the same mail, and a single-user test would
    pass against it. C asked for nothing immediate: "no mail" is a preference."""
    _agent, _project, item = world
    only_comments = await make_user(db, name="Ada", email=f"a-{uuid.uuid4().hex[:8]}@example.com")
    everything = await make_user(db, name="Bo", email=f"b-{uuid.uuid4().hex[:8]}@example.com")
    inbox_only = await make_user(db, name="Cyd", email=f"c-{uuid.uuid4().hex[:8]}@example.com")
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
    """`email_types: []` with the digest on still mails, once. The digest loop opens
    its own session and cannot see uncommitted rows, so its SELECTION (`emailed_at IS
    NULL`, verbatim) and composition are asserted: two rows in, two lines out."""
    _agent, _project, item = world
    inbox_only = await make_user(db, name="Cyd", email=f"c-{uuid.uuid4().hex[:8]}@example.com")
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
    """No prefs row = each kind's default channel: a mention mails as it happens,
    a state change on something merely watched waits for the digest. Both halves are
    asserted — widening the default is only right if it stopped somewhere."""
    _agent, _project, item = world
    assert notify_rules.resolve(NotificationType.MENTIONED).email
    assert not notify_rules.resolve(NotificationType.STATE_CHANGED).email
    newcomer = await make_user(db, name="Nia", email=f"n-{uuid.uuid4().hex[:8]}@example.com")
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
    """RADD-978 end to end: `participant_added` mails by default. The recipient
    holds nothing on the project; they pass the read gate through the Baseline's
    `item.read@participant`, i.e. through the row being announced."""
    agent, project, item = world
    colleague = await make_user(db, name="Colleague", email=f"p-{uuid.uuid4().hex[:8]}@example.com")
    assert await notify_service.get_prefs(db, colleague.id) is None, "the absence IS the fixture"
    assert notify_rules.resolve(NotificationType.PARTICIPANT_ADDED).email

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
    """A preferences row from the `d686emailtypes` backfill predates this type, and no
    migration switches on a channel nobody asked for: inbox row, no mail. The row is
    left UNSTAMPED, so the digest still carries it — a channel choice, not silence."""
    agent, _project, item = world
    settled = await make_user(db, name="Settled", email=f"s-{uuid.uuid4().hex[:8]}@example.com")
    # Verbatim what the migration wrote — the point is a row that predates the type.
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
    """`mailer._comment_id` resolved an ITEM event's `entity_id` (the item) as a
    comment id, killing the tick on a foreign key. Every non-comment case here used
    `event_id=None`, the one shape that cannot reach the lookup — so this one has one."""
    agent, project, item = world
    assignee = await make_user(
        db, name="Ash Assignee", email=f"as-{uuid.uuid4().hex[:8]}@example.com"
    )
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
    """Drives `_handle_item_event` over a REAL item event: reading a top-level
    `project_id` after RADD-922 nested the payload raised inside the consumer's
    SAVEPOINT (logged, skipped), silently killing `assigned`/`state_changed`/mentions."""
    agent, project, item = world
    assignee = await make_user(db, name="Ash", email=f"ash-{uuid.uuid4().hex[:8]}@example.com")
    named = await make_user(db, name="Nina Named", email=f"n-{uuid.uuid4().hex[:8]}@example.com")
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
    watcher = await make_user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
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
    watcher = await make_user(db, name="Ava", email=f"a-{uuid.uuid4().hex[:8]}@example.com")
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
    departed = await make_user(
        db, name="Gone", email=f"g-{uuid.uuid4().hex[:8]}@example.com", active=False
    )
    addressless = await make_user(db, name="No Mail", email="")
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
    """RADD-996: a service account is not a mailbox. The skip is PERMANENT, so the row
    is stamped like the inactive case. `dials`, not `sent`: a message never composed
    still costs a connection if the loop reaches the relay."""
    _agent, _project, item = world
    robot = await _service_account(db)
    await _notify(db, robot, NotificationType.COMMENTED, item, excerpt="Any update?")

    assert await mailer.run_batch(db) == 0

    assert _FakeSmtp.dials == 0, "the relay was dialled for an address that does not receive"
    (row,) = await _rows(db, robot.id)
    assert row.emailed_at is not None, "unstamped means the digest tries the same address"
    # The control: the same batch, one line later, with a person on it.
    human = await make_user(db, name="Hana", email=f"h-{uuid.uuid4().hex[:8]}@example.com")
    await _notify(db, human, NotificationType.COMMENTED, item, excerpt="Any update?")
    assert await mailer.run_batch(db) == 1
    assert _FakeSmtp.dials == 1


async def test_the_digest_skips_a_service_account_and_stamps_it(
    db, world, relay, env_relay, quiet_backlog
):
    """The digest loop, same skip. `state_changed` is not mailed by default, so these
    rows are the digest's by construction."""
    _agent, _project, item = world
    robot = await _service_account(db)
    human = await make_user(db, name="Hana", email=f"h-{uuid.uuid4().hex[:8]}@example.com")
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


# --- every user-addressed email says how to stop it (RADD-985) ----------------


PREFERENCES_URL = f"{BASE_URL}/settings/notifications"


def _html(message: EmailMessage) -> str:
    return message.get_body(("html",)).get_content()


async def test_a_notification_email_carries_list_unsubscribe_and_a_preferences_link(
    db, world, relay, sender_row, quiet_backlog
):
    """Every notification email carries `List-Unsubscribe` and a link to
    `/settings/notifications`. The caller's headers share a dict with
    Reply-To/In-Reply-To/References and must not displace them, or unsubscribing
    would cost a customer their thread."""
    agent, project, item = world
    watcher = await make_user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
    await notify_service.add_watchers(db, item.id, [agent.id, watcher.id])
    await _grant(db, watcher, BuiltinRoleKey.MEMBER, project.id)
    await _comment(db, item, agent, "Restarted it.")
    await consumer._consume(db, watch_only=False)

    assert await mailer.run_batch(db) == 1

    message = _addressed(relay, watcher.email)[0]
    assert str(message["List-Unsubscribe"]) == f"<{PREFERENCES_URL}>"
    assert str(message["Reply-To"]) == RELAY_REPLY_TO, "the thread's headers still win"
    assert f"Notification settings: {PREFERENCES_URL}" in _text(message)
    assert f'href="{PREFERENCES_URL}"' in _html(message)
    assert "Notification settings" in _html(message)


async def test_the_digest_carries_the_header_and_the_link_in_both_parts(
    db, world, relay, env_relay, quiet_backlog
):
    """The slower channel, through `send_plain` — the one with no item and so
    nothing of the transport's to merge with; its headers go out as given."""
    _agent, _project, item = world
    human = await make_user(db, name="Hana", email=f"h-{uuid.uuid4().hex[:8]}@example.com")
    await _notify(db, human, NotificationType.STATE_CHANGED, item, **{"from": "Open", "to": "Done"})

    assert await emailer.run_batch(db) == 1

    message = _addressed(relay, human.email)[0]
    assert str(message["List-Unsubscribe"]) == f"<{PREFERENCES_URL}>"
    assert f"Notification settings: {PREFERENCES_URL}" in _text(message)
    assert f'href="{PREFERENCES_URL}"' in _html(message)
    assert f"{BASE_URL}/inbox" in _text(message), "the inbox link is still offered"


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
    """RADD-997: a failed row used to be re-selected every 5-second tick for 24 hours.
    It now carries its own backoff; the second tick is the assertion — the relay is
    not dialled at all."""
    _agent, _project, item = world
    watcher = await make_user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
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
    """Giving up stamps the row — unstamped, the digest (`emailed_at IS NULL`) would
    retry an address that refused four times. `mail.failed` fires on the FIRST and
    LAST failure only: it answers "did this person hear from us"."""
    _agent, _project, item = world
    watcher = await make_user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
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
    watcher = await make_user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
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


# With NO transport registered (mailintake disabled) there is no env-relay copy
# any more: the rows are recorded undeliverable and the inbox is untouched —
# `test_notify_plugin_sockets.py` drives that against the real plugin (RADD-1385).


async def test_nothing_is_stamped_when_there_is_nowhere_to_send_from(
    db, world, relay, quiet_backlog, no_senders, monkeypatch
):
    """No sender row and no env relay: the rows stay pending. Stamping them
    would silently drop the notification email of every instance that has not
    configured SMTP yet."""
    _agent, _project, item = world
    monkeypatch.setattr(settings, "smtp_host", "")
    watcher = await make_user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
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
    """A notification email carries the sender's Reply-To and its Message-ID is stored
    against the item, so a plain Reply lands on the issue as a comment."""
    agent, project, item = world
    watcher = await make_user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
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
    watcher = await make_user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
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
    """RADD-979: a ticket that arrived at the support desk is mailed to watchers AS
    the desk, although notify knows nothing about sources — the identity is resolved
    once, in `transport._sender`, and every caller rides it."""
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

    watcher = await make_user(db, name="Wanda", email=f"w-{uuid.uuid4().hex[:8]}@example.com")
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


# --- the channels are independent (spec 118) ----------------------------------


async def _cell(db, user: User, kind: NotificationType, channel: Channel) -> None:
    """One cell, in every relationship column — the rest left to the defaults."""
    await notify_service.set_rules(
        db,
        user.id,
        [(scope, None, {kind.value: channel.value}) for scope in RELATIONSHIP_SCOPES],
    )


async def test_email_without_inbox_mails_and_leaves_no_inbox_row(
    db, world, relay, sender_row, quiet_backlog
):
    """Email-only, end to end (spec 118): the decision lives on the row's COLUMNS, so
    the row exists to be mailed and the inbox never shows it."""
    _agent, _project, item = world
    mail_only = await make_user(db, name="Mo", email=f"m-{uuid.uuid4().hex[:8]}@example.com")
    await _cell(db, mail_only, NotificationType.COMMENTED, Channel.EMAIL)
    await _notify(db, mail_only, NotificationType.COMMENTED, item, excerpt="Any update?")

    assert await mailer.run_batch(db) == 1
    assert len(_addressed(relay, mail_only.email)) == 1
    # The row is there — it had to be, to be mailed — and the inbox does not
    # show it, nor does the badge count it.
    (row,) = await _rows(db, mail_only.id)
    assert (row.inbox, row.email) == (False, True)
    assert await notify_service.list_notifications(db, mail_only.id) == []
    assert await notify_service.unread_count(db, mail_only.id) == 0


async def test_marking_everything_read_does_not_cancel_a_pending_email_only_send(
    db, world, relay, sender_row, quiet_backlog
):
    """`mailer._pending` skips READ rows, and an email-only row is never listed, so
    "mark all read" sweeping it would silently cancel a send the person asked for.
    `mark_all_read` is scoped to inbox rows for that reason."""
    _agent, _project, item = world
    mail_only = await make_user(db, name="Mo", email=f"m-{uuid.uuid4().hex[:8]}@example.com")
    await _cell(db, mail_only, NotificationType.COMMENTED, Channel.EMAIL)
    await _notify(db, mail_only, NotificationType.COMMENTED, item, excerpt="Any update?")

    await notify_service.mark_all_read(db, mail_only.id)

    (row,) = await _rows(db, mail_only.id)
    assert row.read_at is None, "an inbox sweep must not touch a row the inbox never showed"
    assert await mailer.run_batch(db) == 1


async def test_an_inbox_only_row_is_never_selected_by_the_mailer(
    db, world, relay, sender_row, quiet_backlog
):
    """The other half of the partition, now decided in SQL rather than by a
    per-recipient pass in Python. What the mailer skips stays UNSTAMPED, so the
    digest — whose selection is `emailed_at IS NULL` — still carries it."""
    _agent, _project, item = world
    quiet = await make_user(db, name="Cyd", email=f"c-{uuid.uuid4().hex[:8]}@example.com")
    await _cell(db, quiet, NotificationType.COMMENTED, Channel.INBOX)
    await _notify(db, quiet, NotificationType.COMMENTED, item, excerpt="Any update?")

    assert await mailer.run_batch(db) == 0
    assert _addressed(relay, quiet.email) == []
    (row,) = await _rows(db, quiet.id)
    assert (row.inbox, row.email) == (True, False)
    assert row.emailed_at is None, "the digest can no longer see it"
