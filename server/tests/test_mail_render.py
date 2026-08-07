"""One mail rendering layer (RADD-967), narrowed to the requester (RADD-968).

The outbound reply had NO tests before RADD-967 — which is how it shipped for two
waves as the bare comment body: no author, no issue key, no link, plain text
only. So this file covers both halves of that gap.

- **Who** gets an outbound reply: the external `mail_contact`, and only them.
  RADD-968 deleted the watcher loop here — it was a SECOND fan-out beside the
  one that decides the inbox, and the two disagreed about permissions, teams and
  mutes. Users are mailed by `notify.mailer` now (`test_notify_mailer.py`), so
  what is pinned here is the leg notify structurally cannot serve plus the guard
  against mailing a staff member twice.
- **What it says**: text AND html, both carrying the author, the body and the
  issue URL; the footer differing by why the recipient is on the thread.
- **Escaping**: a comment is markdown, never markup — a `<script>` in a comment
  and a `<b>` in someone's display name arrive as text in the html part.
- **The digest**: nine notification types, nine distinct lines (there used to be
  four, with five types collapsing into "commented"), issue lines linking the
  issue and a page line linking the page.
- **Transport**: `send_message(html_body=…)` produces multipart/alternative with
  the text part FIRST, and still reports the Message-ID that went on the wire.
"""

import uuid
from email.message import EmailMessage

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd import mailrender, smtp
from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.comments import service as comments_service
from radd.modules.comments.schemas import CommentCreate
from radd.modules.comments.types import CommentEntity, CommentEvent
from radd.modules.events import service as events_service
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.mailintake import (
    outbound,
    reply,
    service as mail_service,
    threading,
    transport as mail_transport,
)
from radd.modules.mailintake.models import MailSender
from radd.modules.mailintake.types import MailDirection, MailRecipientKind, MailSenderKind
from radd.modules.notify import emailer, lines, service as notify_service
from radd.modules.notify.models import Notification
from radd.modules.notify.types import NotificationType
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

BASE_URL = "https://radd.example.com"


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture(autouse=True)
def base_url(monkeypatch):
    """Every renderer takes the base URL as an argument; the CALLERS read it off
    settings, which is the seam these tests pin."""
    monkeypatch.setattr(settings, "app_base_url", BASE_URL + "/")  # trailing slash on purpose
    return BASE_URL


@pytest.fixture
async def world(db):
    suffix = uuid.uuid4().hex[:8]
    agent = User(
        email=f"agent-{suffix}@example.com",
        name="Ada Agent",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(agent)
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"MR{suffix[:4].upper()}", name="Mail render")
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


def _sender_row() -> MailSender:
    """A sender row, never added to a session — `_thread_headers` only reads it."""
    return MailSender(
        name="Test relay",
        kind=MailSenderKind.SMTP.value,
        from_address="agent@radd-hq.com",
        reply_to="help@radd-hq.com",
        host="smtp.test",
        port=25,
    )


# --- who gets it -------------------------------------------------------------


async def test_the_outbound_reply_goes_to_the_contact_and_no_watcher(db, world):
    """RADD-968: watchers are notify's fan-out, not this one.

    Mailing them from here too meant a watcher who had lost `item.read` still
    received the comment, a participant-TEAM member received nothing, and a muted
    type was muted in-app only — three disagreements between the mail and the
    inbox that only one fan-out can end.
    """
    agent, _project, item = world
    suffix = uuid.uuid4().hex[:8]
    watcher = await _user(db, name="Wanda Watcher", email=f"wanda-{suffix}@example.com")
    await notify_service.add_watchers(db, item.id, [agent.id, watcher.id, SYSTEM_ACTOR_ID])
    await mail_service.upsert_contact(
        db, item.id, email="Customer@vip.example.com", name="Cass Customer"
    )

    recipients = await reply.recipients_for(db, item.id)

    assert [(r.email, r.kind) for r in recipients] == [
        ("customer@vip.example.com", MailRecipientKind.REQUESTER)
    ]


async def test_an_item_with_no_contact_mails_nobody_from_here(db, world):
    """The whole leg is the external requester. No contact, no outbound reply —
    the people on the issue are reached by notify."""
    _agent, _project, item = world
    await notify_service.add_watchers(db, item.id, [(await _user(db, name="W", email=f"w-{uuid.uuid4().hex[:8]}@example.com")).id])

    assert await reply.recipients_for(db, item.id) == ()


async def test_a_contact_who_is_an_active_user_is_skipped_not_addressed_as_a_customer(db, world):
    """A staff member who once raised a ticket by email is BOTH a contact and a
    user. Notify mails them as a colleague; sending from here as well would be a
    second copy of the same comment, addressed "you contacted us"."""
    _agent, _project, item = world
    staff = await _user(
        db, name="Sam Staff", email=f"sam-{uuid.uuid4().hex[:8]}@example.com"
    )
    await mail_service.upsert_contact(db, item.id, email=staff.email.upper(), name="Sam")

    assert await reply.recipients_for(db, item.id) == ()

    # A DEPARTED account is not a person notify can mail, so the contact stands.
    staff.active = False
    await db.flush()
    assert [r.email for r in await reply.recipients_for(db, item.id)] == [staff.email.lower()]


# --- what it says ------------------------------------------------------------


def _reply(*, author: str = "Ada Agent", body: str = "We have restarted it.") -> reply.OutboundReply:
    return reply.OutboundReply(
        item_id=uuid.uuid4(),
        comment_id=uuid.uuid4(),
        subject="Re: [MR-1] Printer on fire",
        body=body,
        author=author,
        item=mailrender.ItemMail(key="MR-1", title="Printer on fire", base_url=BASE_URL),
        recipients=(),
    )


def test_both_parts_name_the_author_quote_the_comment_and_link_the_issue():
    planned = _reply()
    message = reply.render(planned, reply.Recipient("cass@vip.example.com", "Cass"))
    for part in (message.text, message.html):
        assert "Ada Agent" in part
        assert "We have restarted it." in part
        assert f"{BASE_URL}/issues/MR-1" in part
        assert "[MR-1] Printer on fire" in part


def test_the_footer_says_why_this_address_is_on_the_thread():
    """One comment, one renderer, two channels — and the footer is the only
    thing that differs. A watcher is a colleague following an issue they can
    open; the requester is a customer with no account whose only interface is
    replying. One "you are receiving this" line cannot honestly say both, which
    is why the body is composed per recipient rather than once.
    """
    planned = _reply()
    requester = reply.render(
        planned,
        reply.Recipient("cass@vip.example.com", "Cass", MailRecipientKind.REQUESTER),
    )
    # RADD-968: the watcher half is notify's, and it passes its OWN wording —
    # `mailrender` takes the reason as text so neither module imports the other.
    watcher = mailrender.comment_reply(
        planned.item,
        author=planned.author,
        body=planned.body,
        reason=lines.MAIL_REASON_TEMPLATE.format(key="MR-1"),
    )
    assert "follow MR-1" in watcher.text
    assert "contacted us about MR-1" in requester.text
    assert watcher.text != requester.text
    assert requester.html != watcher.html


def test_nothing_a_person_typed_survives_as_markup():
    """A comment is markdown and a display name is free text. Rendering either
    would mean shipping user-authored html into a mail client."""
    message = reply.render(
        _reply(author="<b>Eve</b>", body="<script>alert(1)</script>\nsecond line"),
        reply.Recipient("cass@vip.example.com", "Cass"),
    )
    assert "<script>" not in message.html
    assert "<b>Eve</b>" not in message.html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in message.html
    assert "&lt;b&gt;Eve&lt;/b&gt;" in message.html
    # Line breaks are kept — as markup WE emit, from text we escaped.
    assert "second line" in message.html
    assert message.html.count("<br>") == 1


def test_a_trailing_slash_on_the_base_url_does_not_double_up():
    assert mailrender.issue_url("https://radd.example.com/", "MR-1") == f"{BASE_URL}/issues/MR-1"
    assert mailrender.page_url(BASE_URL, "ops", "runbook") == f"{BASE_URL}/pages/ops/runbook"
    assert mailrender.inbox_url(BASE_URL + "//") == f"{BASE_URL}/inbox"


async def test_the_planned_reply_names_the_author_and_addresses_the_contact(db, world):
    """The plan is the ingredients, not a finished message: threading and the
    subject are resolved by the transport at SEND time (RADD-968), so nothing
    here can go stale between planning and delivery."""
    agent, _project, item = world
    await mail_service.upsert_contact(
        db, item.id, email=f"cass-{uuid.uuid4().hex[:8]}@vip.example.com", name="Cass"
    )
    comment = await comments_service.create_comment(
        db, item.id, CommentCreate(body="Engineer dispatched."), agent
    )
    events = await events_service.query_events(
        db,
        entity_type=CommentEntity.COMMENT.value,
        entity_id=str(comment.id),
        event_types=[CommentEvent.CREATED.value],
        limit=1,
    )
    planned = await outbound._plan_reply(db, events[0])

    assert planned is not None
    # The author ref the event has always carried, and outbound never read.
    assert planned.author == "Ada Agent"
    assert planned.item.key.endswith(f"-{item.number}")
    assert planned.item.base_url == BASE_URL + "/"
    assert [r.kind for r in planned.recipients] == [MailRecipientKind.REQUESTER]
    message = reply.render(planned, planned.recipients[0])
    assert "Ada Agent" in message.text
    assert f"{BASE_URL}/issues/{planned.item.key}" in message.html


async def test_the_thread_subject_survives_a_rename(db, world):
    """Subject continuity, now pinned at the seam that decides it: the ORIGINAL
    stored subject with one `Re: `, never re-derived from the item title —
    re-deriving splits the conversation in every participant's client on the
    next rename."""
    _agent, _project, item = world
    await threading.record(
        db,
        message_id="<orig@ext>",
        item_id=item.id,
        direction=MailDirection.INBOUND,
        subject="Printer on fire again",
    )
    row = _sender_row()
    headers, subject = await mail_transport._thread_headers(
        db, item.id, row=row, subject="[MR-1] A totally different title"
    )

    assert subject == "Re: Printer on fire again"
    assert headers["In-Reply-To"] == "<orig@ext>"
    assert headers["References"] == "<orig@ext>"
    assert headers["Reply-To"] == row.reply_to


# --- the digest --------------------------------------------------------------

#: One representative payload per type, in `NotificationType` order.
DIGEST_PAYLOADS = {
    NotificationType.ASSIGNED: {},
    NotificationType.MENTIONED: {"source": "comment", "excerpt": "look at this"},
    NotificationType.STATE_CHANGED: {"from": "To Do", "to": "In Progress"},
    NotificationType.COMMENTED: {"excerpt": "any update?"},
    NotificationType.SLA_BREACH: {"kind": "response", "policy": "Support"},
    NotificationType.SLA_DUE_SOON: {"kind": "response", "policy": "Support"},
    NotificationType.AUTOMATION: {"message": "Escalated to tier 2", "rule": "Escalate"},
    NotificationType.APPROVAL: {"action": "requested", "to_state": "Released"},
    NotificationType.PAGE_UPDATED: {
        "title": "Render farm runbook",
        "space_slug": "ops",
        "page_slug": "render-farm-runbook",
    },
}


def _notification(type_: NotificationType, payload: dict) -> Notification:
    item_fields = (
        {}
        if type_ is NotificationType.PAGE_UPDATED
        else {"item_key": "MR-1", "item_title": "Printer on fire"}
    )
    return Notification(
        user_id=uuid.uuid4(),
        type=type_.value,
        payload={"actor_name": "Ada Agent", **item_fields, **payload},
    )


def test_every_notification_type_gets_its_own_line():
    """The bug this closes: the headline had four branches and an else, so an SLA
    breach, an approval request, an automation message and a wiki page edit all
    arrived as "Someone commented"."""
    rendered = {
        type_: mailrender.digest_line(
            lines.entry(_notification(type_, payload), {})
        ).text
        for type_, payload in DIGEST_PAYLOADS.items()
    }
    assert set(rendered) == set(NotificationType), "a type with no representative payload"
    assert len(set(rendered.values())) == len(NotificationType), f"duplicate lines: {rendered}"
    assert "Ada Agent assigned you" in rendered[NotificationType.ASSIGNED]
    assert "To Do → In Progress" in rendered[NotificationType.STATE_CHANGED]
    assert "breached" in rendered[NotificationType.SLA_BREACH]
    assert "due soon" in rendered[NotificationType.SLA_DUE_SOON]
    assert "Escalated to tier 2" in rendered[NotificationType.AUTOMATION]
    assert "requested your approval to move to Released" in rendered[NotificationType.APPROVAL]


def test_an_issue_line_links_the_issue_and_a_page_line_links_the_page():
    """`page_updated` carries no item at all (RADD-719) — it used to be rendered
    with `/issues/` and an empty key, i.e. a link to nothing."""
    commented = lines.entry(
        _notification(NotificationType.COMMENTED, DIGEST_PAYLOADS[NotificationType.COMMENTED]), {}
    )
    page = lines.entry(
        _notification(
            NotificationType.PAGE_UPDATED, DIGEST_PAYLOADS[NotificationType.PAGE_UPDATED]
        ),
        {},
    )
    assert commented.url == f"{BASE_URL}/issues/MR-1"
    assert page.url == f"{BASE_URL}/pages/ops/render-farm-runbook"


def test_a_notification_with_no_item_key_carries_no_link():
    """Automation notifications carry `{message, rule}` and nothing else, so the
    line degrades to the message rather than to `/issues/` with nothing after."""
    entry = lines.entry(
        Notification(
            user_id=uuid.uuid4(),
            type=NotificationType.AUTOMATION.value,
            payload={"message": "Escalated", "rule": "Escalate"},
        ),
        {},
    )
    assert entry.url == ""
    assert "/issues/" not in mailrender.digest_line(entry).text


def test_the_actor_is_resolved_from_the_id_when_the_payload_has_no_name():
    """`pages.watchers` writes its own payload and never included `actor_name`,
    so every watched-page line read "Someone edited …"."""
    actor_id = uuid.uuid4()
    notification = _notification(
        NotificationType.PAGE_UPDATED, DIGEST_PAYLOADS[NotificationType.PAGE_UPDATED]
    )
    notification.payload = {
        key: value for key, value in notification.payload.items() if key != "actor_name"
    }
    notification.actor_id = actor_id
    anonymous = mailrender.digest_line(lines.entry(notification, {})).text
    assert "Someone edited the page" in anonymous
    named = lines.entry(notification, {actor_id: "Hussein Jarrar"})
    line = mailrender.digest_line(named).text
    assert "Hussein Jarrar edited the page" in line
    # The title is the line's subject (and its link), printed once.
    assert line.count("Render farm runbook") == 1


def test_the_digest_renders_both_parts_and_always_offers_the_inbox():
    message = emailer.compose(
        [_notification(type_, payload) for type_, payload in DIGEST_PAYLOADS.items()], {}
    )
    for part in (message.text, message.html):
        assert f"{BASE_URL}/inbox" in part
        assert f"{BASE_URL}/issues/MR-1" in part
        assert f"{BASE_URL}/pages/ops/render-farm-runbook" in part
    assert message.html.lstrip().startswith("<html")


# --- transport ---------------------------------------------------------------


class _FakeSmtp:
    """Enough of smtplib.SMTP to capture one composed message."""

    sent: list[EmailMessage] = []

    def __init__(self, *args, **kwargs):
        pass

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


def test_send_message_with_html_produces_multipart_alternative(monkeypatch):
    _FakeSmtp.sent = []
    monkeypatch.setattr(smtp.smtplib, "SMTP", _FakeSmtp)
    message_id = smtp.send_message(
        "wanda@example.com",
        "Re: [MR-1] Printer on fire",
        "plain text part",
        html_body="<html><body>rich part</body></html>",
        config=smtp.SmtpConfig(
            host="smtp.test",
            port=25,
            username="",
            password="",
            starttls=False,
            from_address="agent@radd-hq.com",
        ),
    )
    sent = _FakeSmtp.sent[-1]
    assert sent.get_content_type() == "multipart/alternative"
    subtypes = [part.get_content_subtype() for part in sent.iter_parts()]
    # Ordered worst-to-best: a client shows the LAST part it can render.
    assert subtypes == ["plain", "html"]
    assert "plain text part" in sent.get_body(("plain",)).get_content()
    assert "rich part" in sent.get_body(("html",)).get_content()
    # RADD-955: the id threading is stored against is read back off the message.
    assert message_id == str(sent["Message-ID"])


def test_send_message_without_html_stays_a_single_plain_part(monkeypatch):
    _FakeSmtp.sent = []
    monkeypatch.setattr(smtp.smtplib, "SMTP", _FakeSmtp)
    smtp.send_message(
        "wanda@example.com",
        "subject",
        "plain only",
        config=smtp.SmtpConfig(
            host="smtp.test",
            port=25,
            username="",
            password="",
            starttls=False,
            from_address="agent@radd-hq.com",
        ),
    )
    assert _FakeSmtp.sent[-1].get_content_type() == "text/plain"
