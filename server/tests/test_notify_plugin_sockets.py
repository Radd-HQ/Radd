"""RADD-1385 — notify (core) reaches pages, participants and mailintake (optional)
only through kernel sockets, pinned against the REAL plugins withdrawn the way the
plugin manager does (`registries.unregister_plugin`):

* pages withdrawn — a page comment plans nothing and does not raise, a queued page
  row fails the mail re-check; registered, the event reaches the page's watcher;
* mailintake withdrawn — an email-channel notification still lands in the inbox and
  both mail loops record it UNDELIVERABLE (relay never dialled, `emailed_at` NULL,
  one `notification.undeliverable` each); registered again, the next batch carries
  the rows still inside the retry window and leaves the older ones as they were.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from radd import smtp
from radd.config import settings
from radd.kernel.registry import registries
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.comments import service as comments_service
from radd.modules.comments.schemas import CommentCreate
from radd.modules.comments.types import CommentParentType
from radd.modules.events import service as events_service
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.mailintake import plugin as mailintake_plugin
from radd.modules.mailintake.models import MailSender
from radd.modules.notify import consumer, emailer, mailer, service as notify_service
from radd.modules.notify.authorization import notification_readable
from radd.modules.notify.models import Notification
from radd.modules.notify.transport import NotificationMailKind
from radd.modules.notify.types import NotificationDelivery, NotificationType, NotifyEvent
from radd.modules.pages import plugin as pages_plugin, service as pages_service, spaces
from radd.modules.pages import watchers as page_watchers
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

from _factories import make_user


class _Relay:
    """Enough of smtplib.SMTP to count connections: "nothing was sent" must
    mean the relay was never dialled, not that it was dialled to say nothing."""

    dials = 0

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
        pass


@pytest.fixture
def relay(monkeypatch):
    """The env relay mailintake falls back to, faked. Sender ROWS other tests
    committed are disabled per test (`_quiet`), so this is the one way out."""
    _Relay.dials = 0
    monkeypatch.setattr(smtp.smtplib, "SMTP", _Relay)
    monkeypatch.setattr(settings, "smtp_host", "smtp.env.test")
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_from_address", "agent@radd.example.com")
    return _Relay


async def _quiet(db) -> None:
    """Both loops select GLOBALLY: drop what other tests left the channel owing,
    and disable their sender rows — inside this transaction, so it rolls back."""
    await db.execute(
        update(Notification)
        .where(Notification.delivery != NotificationDelivery.SENT.value)
        .values(delivery=NotificationDelivery.DROPPED.value)
    )
    await db.execute(update(MailSender).values(enabled=False))


# Recipients are admins, so every one passes the read gate and a refusal can
# only come from the thing under test.


async def _drain(db, after: int) -> None:
    """The real dispatcher over this test's events, raising instead of logging."""
    for event in await events_service.read_after(db, after, 200):
        if not event.silent and consumer.handles(event.event_type):
            await consumer._handle(db, event, watch_only=False)


async def _rows(db, user: User) -> list[Notification]:
    return list((await db.execute(select(Notification).where(Notification.user_id == user.id))).scalars())


async def test_a_withdrawn_wiki_notifies_nobody_and_a_registered_one_its_watchers(db):
    author, watcher = (
        await make_user(db, role=InstanceRole.ADMIN, name="Author"),
        await make_user(db, role=InstanceRole.ADMIN, name="Watcher"),
    )
    slug = f"sock-{uuid.uuid4().hex[:8]}"
    space = await spaces.create_space(db, PageSpaceCreate(name=slug, slug=slug), author.id)
    page = await pages_service.create_page(
        db, PageCreate(space_id=space.id, title="Runbook", slug="runbook", body="v1"), author.id
    )
    await page_watchers.watch(db, page.id, watcher.id)
    head = await events_service.latest_event_id(db)
    await comments_service.create_comment(
        db, page.id, CommentCreate(body="Out of date."), author,
        entity_type=CommentParentType.PAGE.value,
    )
    await db.flush()

    registries.unregister_plugin(pages_plugin)
    try:
        assert not consumer.handles("page.updated"), "a withdrawn subject's events are not claimed"
        await _drain(db, head)  # the comment is still in the stream: it must not raise
        assert await _rows(db, watcher) == [], "nobody may vouch for a page, so nobody hears"
    finally:
        registries.register_plugin(pages_plugin)

    await _drain(db, head)
    (row,) = await _rows(db, watcher)
    assert row.type == NotificationType.COMMENTED.value and row.item_id is None
    assert row.payload["page_slug"] == "runbook" and row.payload["subject_type"] == "page"
    assert await notification_readable(db, row, watcher)

    # The mail loops' re-check asks the SAME provider: withdrawn, a queued page
    # row is no longer deliverable — there is nothing left to answer for it.
    registries.unregister_plugin(pages_plugin)
    try:
        assert not await notification_readable(db, row, watcher)
    finally:
        registries.register_plugin(pages_plugin)


async def _undeliverable_events(db, after: int) -> dict[uuid.UUID, str]:
    return {
        uuid.UUID(event.entity_id): event.payload["kind"]
        for event in await events_service.read_after(db, after, 500)
        if event.event_type == NotifyEvent.NOTIFICATION_UNDELIVERABLE.value
    }


async def test_without_a_transport_email_is_recorded_undeliverable_and_the_inbox_is_not(
    db, relay, monkeypatch
):
    await _quiet(db)
    agent, assignee = (
        await make_user(db, role=InstanceRole.ADMIN, name="Agent"),
        await make_user(db, role=InstanceRole.ADMIN, name="Assignee"),
    )
    suffix = uuid.uuid4().hex[:4].upper()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SK{suffix}", name="Socket mail")
    )

    registries.unregister_plugin(mailintake_plugin)
    try:
        head = await events_service.latest_event_id(db)
        item = await items_service.create_item(
            db, ItemCreate(project_id=project.id, title="Printer on fire", assignee_id=assignee.id), agent
        )
        await db.flush()
        await _drain(db, head)
        (row,) = await _rows(db, assignee)
        # In-app delivery never depended on mail: the row is in the inbox, and
        # the recipient's verdict still asks for email (`assigned` = both).
        assert row.type == NotificationType.ASSIGNED.value and row.inbox and row.email
        # An inbox-only row for the digest's half of the same answer.
        digest_row = await notify_service.create_notification(
            db, user_id=assignee.id, type_=NotificationType.STATE_CHANGED, event_id=None,
            item_id=item.id, actor_id=agent.id, payload={"from": "Open", "to": "Done"},
        )
        assert digest_row is not None and digest_row.inbox and not digest_row.email

        assert await mailer.run_batch(db) == 0
        assert await emailer.run_batch(db) == 0
        await db.refresh(row)
        await db.refresh(digest_row)
        for undeliverable in (row, digest_row):
            assert undeliverable.delivery == NotificationDelivery.UNDELIVERABLE.value
            assert undeliverable.emailed_at is None, "recorded undeliverable, not as emailed"
        assert await _undeliverable_events(db, head) == {
            row.id: NotificationMailKind.NOTIFICATION.value,
            digest_row.id: NotificationMailKind.DIGEST.value,
        }
        # The next tick without a transport has nothing new to record or announce.
        assert await mailer.run_batch(db) == 0 and await emailer.run_batch(db) == 0
        assert len(await _undeliverable_events(db, head)) == 2
        assert relay.dials == 0
        inbox = await notify_service.list_notifications(db, assignee.id)
        assert {n.id for n in inbox} == {row.id, digest_row.id}
    finally:
        registries.register_plugin(mailintake_plugin)

    # Registered again: the next batch carries the rows recorded undeliverable —
    # the mailer the email-channel row, the digest the inbox-only one — beside a
    # fresh row (the control: the zero above was the missing transport, not an
    # unmailable row), and only a send sets `emailed_at`.
    again = await notify_service.create_notification(
        db, user_id=assignee.id, type_=NotificationType.ASSIGNED, event_id=None,
        item_id=item.id, actor_id=agent.id, payload={"item_key": item.key, "item_title": item.title},
    )
    assert again is not None and again.email
    assert await mailer.run_batch(db) == 2
    assert relay.dials == 2
    await db.refresh(row)
    assert row.delivery == NotificationDelivery.SENT.value and row.emailed_at is not None
    assert await emailer.run_batch(db) == 1
    assert relay.dials == 3
    await db.refresh(digest_row)
    assert digest_row.delivery == NotificationDelivery.SENT.value and digest_row.emailed_at is not None

    # A row recorded undeliverable longer ago than the retry window is not retried:
    # a transport re-enabled after a week must not flush a week of mail.
    monkeypatch.setattr(settings, "notify_undeliverable_retry_hours", 1)
    stale = await notify_service.create_notification(
        db, user_id=assignee.id, type_=NotificationType.ASSIGNED, event_id=None,
        item_id=item.id, actor_id=agent.id, payload={"item_key": item.key, "item_title": item.title},
    )
    registries.unregister_plugin(mailintake_plugin)
    try:
        assert await mailer.run_batch(db) == 0
    finally:
        registries.register_plugin(mailintake_plugin)
    await db.execute(
        update(Notification)
        .where(Notification.id == stale.id)
        .values(created_at=mailer.utcnow() - timedelta(hours=2))
    )
    assert await mailer.run_batch(db) == 0 and await emailer.run_batch(db) == 0
    await db.refresh(stale)
    assert stale.delivery == NotificationDelivery.UNDELIVERABLE.value and stale.emailed_at is None
    assert relay.dials == 3
