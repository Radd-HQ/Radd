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
from sqlalchemy import select, update
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
    intake,
    outbound,
    parsing,
    reply,
    service as mail_service,
    threading,
    transport as mail_transport,
)
from radd.modules.mailintake.models import MailMessage, MailSender
from radd.modules.mailintake.types import MailDirection, MailRecipientKind, MailSenderKind
from radd.modules.notify import emailer, lines, service as notify_service
from radd.modules.notify.models import Notification
from radd.modules.notify.types import NotificationType
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope

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


async def test_the_reply_fans_out_to_every_contact_primary_first(db, world):
    """RADD-980. A customer CCs their colleague, or the colleague answers instead;
    both are on the thread, and a reply that reaches one of them is a reply the
    other never saw — with nothing anywhere admitting it, because a message that
    WAS sent looks exactly like a message sent to everybody.

    The order is pinned too: primary, then the rest alphabetically. Contacts
    captured from ONE message share a transaction timestamp, so `created_at`
    cannot separate them and an id tiebreak would reorder the issue rail on
    every read.
    """
    _agent, _project, item = world
    await mail_service.upsert_contact(db, item.id, email="cass@vip.example.com", name="Cass")
    await mail_service.upsert_contact(
        db, item.id, email="Ops@vip.example.com", name="Ops", copied_in=True
    )
    await mail_service.upsert_contact(db, item.id, email="bill@vip.example.com", copied_in=True)

    assert [r.email for r in await reply.recipients_for(db, item.id)] == [
        "cass@vip.example.com",  # the primary leads: she raised it
        "bill@vip.example.com",
        "ops@vip.example.com",
    ]


async def test_one_staff_contact_no_longer_silences_the_whole_reply(db, world):
    """The active-user skip is per ADDRESS, not per item.

    It was written when a ticket had at most one contact, so `return ()` was the
    same statement. With three it is not: a colleague copied into a customer's
    thread would have cancelled the customer's reply as well.
    """
    _agent, _project, item = world
    staff = await _user(db, name="Sam Staff", email=f"sam-{uuid.uuid4().hex[:8]}@example.com")
    await mail_service.upsert_contact(db, item.id, email="cass@vip.example.com", name="Cass")
    await mail_service.upsert_contact(db, item.id, email=staff.email, copied_in=True)

    assert [r.email for r in await reply.recipients_for(db, item.id)] == ["cass@vip.example.com"]


async def test_a_copied_in_address_never_becomes_the_requester(db, world):
    """`contact_for_item` is what CSAT, the automation `contact` role and the
    singular endpoint all mean by "the requester", and RADD-980 must not let a
    bystander inherit it: an issue whose only external address was COPIED IN has
    no requester here, so those seams fall through to the reporter — who, on
    exactly that shape of ticket, is the colleague who raised it."""
    _agent, _project, item = world
    await mail_service.upsert_contact(
        db, item.id, email="watching@vip.example.com", copied_in=True
    )

    assert await mail_service.contact_for_item(db, item.id) is None
    assert [c.email for c in await mail_service.contacts_for_item(db, item.id)] == [
        "watching@vip.example.com"
    ]

    # …and the first person who actually WRITES takes the badge.
    await mail_service.upsert_contact(db, item.id, email="cass@vip.example.com", name="Cass")
    primary = await mail_service.contact_for_item(db, item.id)
    assert primary is not None and primary.email == "cass@vip.example.com"


async def test_a_contacts_last_message_is_their_own(db, world):
    """One column shared by three people is a fact about none of them. It fed the
    outbound In-Reply-To before `mail_messages` existed, and a CC's reply
    overwriting the requester's own was invisible either way."""
    _agent, _project, item = world
    await mail_service.upsert_contact(
        db, item.id, email="cass@vip.example.com", message_id="<cass-1@ext>"
    )
    await mail_service.upsert_contact(
        db, item.id, email="ops@vip.example.com", message_id="<ops-1@ext>", copied_in=True
    )

    stored = {c.email: c.last_message_id for c in await mail_service.contacts_for_item(db, item.id)}
    assert stored == {"cass@vip.example.com": "<cass-1@ext>", "ops@vip.example.com": "<ops-1@ext>"}


async def test_two_contacts_on_one_item_are_storable_and_one_address_is_not_twice(db, world):
    """The reshape (`d980contacts`) stated as its observable consequence.

    `item_id` was the PRIMARY KEY, so the first assertion was a unique violation
    until this migration; `(item_id, email)` is now the constraint, so the second
    still is — which is what makes `upsert_contact` idempotent across a thread
    rather than accumulating a row per message.
    """
    from sqlalchemy.exc import IntegrityError

    from radd.modules.mailintake.models import MailContact

    _agent, _project, item = world
    await mail_service.upsert_contact(db, item.id, email="one@vip.example.com")
    await mail_service.upsert_contact(db, item.id, email="two@vip.example.com", copied_in=True)
    assert len(await mail_service.contacts_for_item(db, item.id)) == 2

    db.add(MailContact(item_id=item.id, email="one@vip.example.com"))
    with pytest.raises(IntegrityError):
        await db.flush()


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
    # RADD-985: the settings link is the USER-addressed caller's to add, and
    # the requester path never adds it — a customer has no matrix to open, and
    # the reply-to-comment wording is already how they take part.
    for part in (requester.text, requester.html):
        assert mailrender.NOTIFICATION_SETTINGS_LABEL not in part
        assert mailrender.PREFERENCES_PATH not in part


def test_user_addressed_renderers_link_the_notification_settings_in_both_parts():
    """RADD-985: the three renderers notify mails through — the comment reply,
    the single notice and the digest — print where the mail is turned off in
    the text half and the html half, and the header helper spells the same URL
    in angle brackets. Absent the argument, nothing is printed and no header is
    made: an empty `List-Unsubscribe` is worse than none."""
    preferences = mailrender.preferences_url(BASE_URL + "/")
    assert preferences == f"{BASE_URL}/settings/notifications"
    item = mailrender.ItemMail(key="MR-1", title="Printer on fire", base_url=BASE_URL)
    entry = mailrender.DigestEntry(headline="Ada Agent moved Open → Done", subject="[MR-1] x")
    rendered = [
        mailrender.comment_reply(
            item, author="Ada", body="Restarted.", reason="because", preferences=preferences
        ),
        mailrender.notice(entry, reason="because", preferences=preferences),
        mailrender.digest([entry], inbox=f"{BASE_URL}/inbox", preferences=preferences),
    ]
    for message in rendered:
        assert f"{mailrender.NOTIFICATION_SETTINGS_LABEL}: {preferences}" in message.text
        assert f'href="{preferences}"' in message.html
        assert message.html.count(mailrender.NOTIFICATION_SETTINGS_LABEL) == 1
    bare = [
        mailrender.comment_reply(item, author="Ada", body="Restarted.", reason="because"),
        mailrender.notice(entry, reason="because"),
        mailrender.digest([entry], inbox=f"{BASE_URL}/inbox"),
    ]
    for message in bare:
        assert mailrender.NOTIFICATION_SETTINGS_LABEL not in message.text
        assert mailrender.NOTIFICATION_SETTINGS_LABEL not in message.html
    assert mailrender.unsubscribe_headers(preferences) == {
        mailrender.LIST_UNSUBSCRIBE_HEADER: f"<{preferences}>"
    }
    assert mailrender.unsubscribe_headers("") == {}


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


async def test_an_agents_mailed_reply_is_relayed_and_excludes_them_from_notify(db, world):
    """RADD-981, at the two seams that read a comment's ACTOR.

    Both were broken by the same fact: a mailed reply was authored by SYSTEM.
    `should_reply` refuses a SYSTEM comment — deliberately, to stop an
    inbound-mail comment echoing straight back out — so an agent who answered a
    customer BY EMAIL was never relayed to that customer, while the same words
    typed into the UI were. And notify excludes the actor from its fan-out, so
    with SYSTEM as the actor the agent was notified of their own reply and
    nobody's exclusion applied.
    """
    from radd.modules.mailintake import parsing as mail_parsing, threading as mail_threading
    from radd.modules.notify import planner

    agent, project, item = world
    colleague = await _user(db, name="Cal", email=f"cal-{uuid.uuid4().hex[:8]}@example.com")
    await mail_service.upsert_contact(db, item.id, email="cass@vip.example.com", name="Cass")
    await mail_threading.record(
        db, message_id="<told@radd>", item_id=item.id, direction=MailDirection.OUTBOUND
    )

    incoming = EmailMessage()
    incoming["Subject"] = "Re: Printer on fire"
    incoming["From"] = f"Ada Agent <{agent.email}>"
    incoming["To"] = "help@radd-hq.com"
    incoming["Message-ID"] = f"<{uuid.uuid4().hex}@example.com>"
    incoming["In-Reply-To"] = "<told@radd>"
    incoming.set_content("Engineer dispatched.")
    raw = incoming.as_bytes()
    outcome = await intake.accept(
        db,
        mail_parsing.parse_email(raw),
        raw=raw,
        default_project_key=project.key,
        own_addresses={"help@radd-hq.com"},
    )
    assert outcome.result is intake.Result.APPENDED

    [event] = await events_service.query_events(
        db,
        entity_type=CommentEntity.COMMENT.value,
        event_types=[CommentEvent.CREATED.value],
        limit=1,
    )
    assert event.actor_id == agent.id, "the actor IS the attribution both seams read"

    planned = await outbound._plan_reply(db, event)
    assert planned is not None, "a SYSTEM-authored reply is refused — this one must not be"
    assert [r.email for r in planned.recipients] == ["cass@vip.example.com"]
    assert "Engineer dispatched." in planned.body

    plan = planner.plan_comment_created(
        event.payload,
        event.actor_id,
        planner.Audience(participating=frozenset({agent.id, colleague.id})),
        frozenset(),
    )
    notified = {n.user_id for n in plan.notifications}
    assert colleague.id in notified and agent.id not in notified


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
    # RADD-978: the issue IS the subject line, so the detail is empty like
    # `assigned` — the headline names the actor and the verb, nothing else.
    NotificationType.PARTICIPANT_ADDED: {},
    # Spec 118's ambient trio — what a SUBSCRIBER to a project, space or team
    # hears about. `created` says only that it was filed (the subject line
    # carries what); `updated` names up to three changed fields, because "Ada
    # updated the issue" in a digest of eleven is a line with no information.
    NotificationType.CREATED: {},
    NotificationType.UPDATED: {"fields": ["priority", "labels"]},
    NotificationType.PAGE_CREATED: {
        "title": "Colour pipeline",
        "space_slug": "ops",
        "page_slug": "colour-pipeline",
    },
}

#: Kinds whose subject is a PAGE — no item key/title in the payload.
_PAGE_TYPES = {NotificationType.PAGE_UPDATED, NotificationType.PAGE_CREATED}


def _notification(type_: NotificationType, payload: dict) -> Notification:
    item_fields = (
        {}
        if type_ in _PAGE_TYPES
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
    assert "added you to the issue" in rendered[NotificationType.PARTICIPANT_ADDED]


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
    """An ITEMLESS automation notification carries `{message, rule}` and nothing
    else (an item-scoped one has carried the ref since RADD-972), so the line
    degrades to the message rather than to `/issues/` with nothing after."""
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
    """Enough of smtplib.SMTP to capture one composed message — and WHICH RELAY
    it was handed to.

    The dial is recorded because from outside the process that is the only thing
    that distinguishes a `mail_senders` ROW from the environment relay
    (RADD-970): the composed message looks the same either way, so a test that
    only inspects the message cannot tell whether the row was used at all.
    """

    sent: list[EmailMessage] = []
    dialled: list[tuple[str, int]] = []

    def __init__(self, host="", port=0, *args, **kwargs):
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


def test_send_message_with_html_produces_multipart_alternative(monkeypatch):
    _FakeSmtp.sent = []
    _FakeSmtp.dialled = []
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
    _FakeSmtp.dialled = []
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


# --- the acknowledgement, on the same transport (RADD-970) --------------------


@pytest.fixture
async def no_senders(db):
    """Disable every `mail_senders` row already committed to the test database.

    `registry.default_sender` reads the table, not a fixture — a row another
    module committed (or an app-startup test seeded from env) would otherwise
    decide which relay these tests dial, and "the row was used" would be true by
    accident. Disabled inside the transaction, so it rolls back with everything.
    """
    await db.execute(update(MailSender).values(enabled=False))


@pytest.fixture
def relay(monkeypatch):
    """A captured SMTP relay. Returns the fake class — `.sent` and `.dialled`."""
    _FakeSmtp.sent = []
    _FakeSmtp.dialled = []
    monkeypatch.setattr(smtp.smtplib, "SMTP", _FakeSmtp)
    return _FakeSmtp


def _row_relay(db) -> MailSender:
    row = MailSender(
        name=f"Rows {uuid.uuid4().hex[:6]}",
        kind=MailSenderKind.SMTP.value,
        is_default=True,
        from_address="agent@radd-hq.com",
        reply_to="help@radd-hq.com",
        host="smtp.rowrelay.test",
        port=2525,
        starttls=False,
    )
    db.add(row)
    return row


async def _requester_wrote(db, item, *, subject="my printer is on fire") -> str:
    """The inbound message intake recorded before the ack fires — on BOTH call
    paths, which commit the intake transaction first for exactly this reason."""
    message_id = f"<{uuid.uuid4().hex}@vip.example>"
    await threading.record(
        db,
        message_id=message_id,
        item_id=item.id,
        direction=MailDirection.INBOUND,
        subject=subject,
    )
    await db.flush()
    return message_id


def test_the_ack_carries_the_issue_link_in_both_parts():
    """RADD-977. RADD-967 left the link out on purpose — "the requester has no
    account, so the link is a login page" — and that reasoning is stale twice
    over: intake PROVISIONS an account for an unknown sender (RADD-828), and on
    an SSO instance the sender is very often a colleague who is already signed
    in. A receipt with no way to look at the thing it acknowledges is a dead end
    for both; a login page is recoverable.

    What must NOT change is which instruction leads. Reply-by-email is the
    interface that works for every requester whether they can sign in or not, so
    it stays first in both parts and the link follows it — asserted by position,
    because "the link is present" is true of a version that buries the sentence.
    """
    item = mailrender.ItemMail(key="MR-1", title="Printer on fire", base_url=BASE_URL + "/")
    # The default template, {{key}} substituted by hand — mailrender no longer
    # renders the ack's prose itself (RADD-1045), only wraps what it is given.
    body = settings.mail_ack_body.replace("{{key}}", item.key)
    message = mailrender.acknowledgement(item, body=body)
    url = f"{BASE_URL}/issues/MR-1"

    assert url in message.text
    assert f'href="{url}"' in message.html
    assert mailrender.ACK_LINK_LABEL in message.text
    assert mailrender.ACK_LINK_LABEL in message.html
    for part in (message.text, message.html):
        assert part.index("reply to this message") < part.index(url), "the link led"
    # The subject mechanics are untouched: the bracketed key is what
    # `parsing.extract_reply_key` threads a header-less reply on.
    assert f"[{item.key}] in the subject" in message.text


async def test_the_ack_leaves_through_the_default_sender_row(
    db, world, relay, no_senders, monkeypatch
):
    """The ack used to dial `radd.smtp` straight off `RADD_SMTP_*`, which meant
    an admin who configured a sender in Settings → Email and set no environment
    got replies and notifications and no receipts — the one message a requester
    always expects.

    With no env relay configured at all, the ROW is what gets dialled, and the
    headers come from the message store rather than a parameter carried by hand.
    """
    _agent, project, item = world
    key = f"{project.key}-{item.number}"
    monkeypatch.setattr(settings, "smtp_host", "")  # nothing to fall back to
    _row_relay(db)
    inbound_id = await _requester_wrote(db, item)

    await mail_service.send_ack(
        db,
        item_id=item.id,
        email="cass@vip.example.com",
        name="Cass Customer",
        item_key=key,
        title=item.title,
    )

    assert relay.dialled == [("smtp.rowrelay.test", 2525)]
    sent = relay.sent[-1]
    # The bracketed key SURVIVES: it is the subject-line threading fallback, and
    # the stored thread subject at this moment is the requester's own, which has
    # no key in it. `pin_subject` exists for this one message.
    assert str(sent["Subject"]) == f"[{key}] {item.title}"
    assert str(sent["In-Reply-To"]) == inbound_id
    assert str(sent["References"]) == inbound_id
    assert str(sent["Reply-To"]) == "help@radd-hq.com"
    assert "Cass Customer" in str(sent["To"])
    assert sent.get_content_type() == "multipart/alternative"  # text + html, as ever
    # RADD-977: the receipt the requester actually receives carries the link.
    assert f"{BASE_URL}/issues/{key}" in sent.get_body(("plain",)).get_content()
    assert f'href="{BASE_URL}/issues/{key}"' in sent.get_body(("html",)).get_content()
    # RADD-985: requester-facing mail says nothing about notification settings —
    # the conversation is their ticket, and there is no matrix to link.
    assert sent.get(mailrender.LIST_UNSUBSCRIBE_HEADER) is None
    assert mailrender.NOTIFICATION_SETTINGS_LABEL not in sent.get_body(("plain",)).get_content()


async def test_pinning_the_subject_changes_nothing_a_client_threads_on(db, world):
    """The design decision, stated where it can be checked: `pin_subject` is a
    property of the SUBJECT LINE alone.

    Its sibling `test_the_thread_subject_survives_a_rename` pins the unpinned
    behaviour the reply consumer depends on — one `Re: ` over the stored subject
    — and this asserts the two differ in exactly that field, so pinning the ack
    cannot quietly become a second threading rule.
    """
    _agent, _project, item = world
    inbound_id = await _requester_wrote(db, item, subject="Printer on fire again")
    row = _sender_row()

    free, free_subject = await mail_transport._thread_headers(
        db, item.id, row=row, subject="[MR-1] A totally different title"
    )
    pinned, pinned_subject = await mail_transport._thread_headers(
        db, item.id, row=row, subject="[MR-1] A totally different title", pin_subject=True
    )

    assert free_subject == "Re: Printer on fire again"
    assert pinned_subject == "[MR-1] A totally different title"
    assert free == pinned == {
        "Reply-To": row.reply_to,
        "In-Reply-To": inbound_id,
        "References": inbound_id,
    }


async def test_the_ack_still_goes_out_through_the_env_relay_when_no_row_exists(
    db, world, relay, no_senders, monkeypatch
):
    """A seed-era instance has no sender row — `seeding` only writes one when
    `RADD_SMTP_HOST` was set at first boot. `send_ack` has always had this
    fallback, and moving it onto the transport must not quietly drop it."""
    _agent, project, item = world
    monkeypatch.setattr(settings, "smtp_host", "relay.env.test")
    monkeypatch.setattr(settings, "smtp_port", 1025)
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_username", "")
    monkeypatch.setattr(settings, "smtp_from_address", "Radd <agent@radd-hq.com>")
    monkeypatch.setattr(settings, "email_ingest_address", "help@radd-hq.com")

    await mail_service.send_ack(
        db,
        item_id=item.id,
        email="cass@vip.example.com",
        name="Cass",
        item_key=f"{project.key}-{item.number}",
        title=item.title,
    )

    assert relay.dialled == [("relay.env.test", 1025)]
    assert str(relay.sent[-1]["Reply-To"]) == "help@radd-hq.com"


async def test_a_reply_to_the_ack_threads_back_onto_the_issue(
    db, world, relay, no_senders, monkeypatch
):
    """Why recording the ack's own Message-ID matters.

    The receipt is the only message most requesters ever get from Radd, so it is
    the one they hit Reply on. Its id previously went nowhere, and the reply fell
    through to the subject key — which a client that rewrites the subject, or a
    person who edits it, does not carry. This subject deliberately has no key in
    it, so nothing but the recorded header can resolve it.
    """
    _agent, project, item = world
    monkeypatch.setattr(settings, "smtp_host", "")
    _row_relay(db)
    await _requester_wrote(db, item)

    await mail_service.send_ack(
        db,
        item_id=item.id,
        email="cass@vip.example.com",
        name="Cass",
        item_key=f"{project.key}-{item.number}",
        title=item.title,
    )
    ack_id = str(relay.sent[-1]["Message-ID"])

    stored = await db.execute(
        select(MailMessage.message_id, MailMessage.direction).where(
            MailMessage.item_id == item.id
        )
    )
    assert (ack_id, MailDirection.OUTBOUND.value) in set(stored.all())

    incoming = EmailMessage()
    incoming["Subject"] = "thanks!"  # no key at all
    incoming["From"] = "Cass <cass@vip.example.com>"
    incoming["To"] = "help@radd-hq.com"
    incoming["Message-ID"] = f"<{uuid.uuid4().hex}@vip.example>"
    incoming["In-Reply-To"] = ack_id
    incoming.set_content("That fixed it.")
    raw = incoming.as_bytes()

    outcome = await intake.accept(
        db,
        parsing.parse_email(raw),
        raw=raw,
        default_project_key=project.key,
        own_addresses=set(),
    )

    assert outcome.result is intake.Result.APPENDED
    assert outcome.item_id == item.id


async def test_a_user_sender_receives_the_receipt_end_to_end(
    db, world, relay, no_senders, monkeypatch
):
    """RADD-995, driven through the whole path rather than the plan alone.

    Intake plans it, the caller acks post-commit, and what leaves the relay is
    the same `[KEY] title` receipt with the issue link a contact has had since
    RADD-977 — which matters most for exactly this sender, since a recognised
    user CAN follow that link.
    """
    agent, project, _ = world
    monkeypatch.setattr(settings, "smtp_host", "")  # nothing to fall back to
    _row_relay(db)

    incoming = EmailMessage()
    incoming["Subject"] = "my laptop will not charge"
    incoming["From"] = f"Ada Agent <{agent.email}>"
    incoming["To"] = "help@radd-hq.com"
    incoming["Message-ID"] = f"<{uuid.uuid4().hex}@example.com>"
    incoming.set_content("It stopped overnight.")
    raw = incoming.as_bytes()
    outcome = await intake.accept(
        db,
        parsing.parse_email(raw),
        raw=raw,
        default_project_key=project.key,
        own_addresses={"help@radd-hq.com"},
    )
    assert outcome.ack is not None, "a recognised user got no receipt at all — the RADD-995 bug"

    await mail_service.send_ack(
        db,
        item_id=outcome.ack.item_id,
        email=outcome.ack.email,
        name=outcome.ack.name,
        item_key=outcome.ack.item_key,
        title=outcome.ack.title,
    )

    sent = relay.sent[-1]
    assert agent.email in str(sent["To"])
    assert str(sent["Subject"]) == f"[{outcome.item_key}] my laptop will not charge"
    # In-Reply-To comes off the inbound row intake recorded, as it does for a contact.
    assert str(sent["In-Reply-To"]) == str(incoming["Message-ID"])
    assert f"{BASE_URL}/issues/{outcome.item_key}" in sent.get_body(("plain",)).get_content()


async def test_the_ack_toggle_still_silences_it(db, world, relay, no_senders, monkeypatch):
    """`RADD_MAIL_SEND_ACK` survives the move — it is a product decision (some
    desks do not want a receipt), not a piece of the env configuration that
    RADD-958 replaced with rows."""
    _agent, project, item = world
    monkeypatch.setattr(settings, "mail_send_ack", False)
    monkeypatch.setattr(settings, "smtp_host", "relay.env.test")
    _row_relay(db)
    await db.flush()

    await mail_service.send_ack(
        db,
        item_id=item.id,
        email="cass@vip.example.com",
        name="Cass",
        item_key=f"{project.key}-{item.number}",
        title=item.title,
    )

    assert relay.sent == [] and relay.dialled == []


# --- the ack body is a scalar setting now (RADD-1045) -------------------------


async def test_an_unset_ack_setting_sends_todays_default_wording(
    db, world, relay, no_senders, monkeypatch
):
    """No override row at all — the cascade falls back to `config.Settings.
    mail_ack_body`, so a fresh instance's receipt is byte-identical to before
    the setting existed."""
    _agent, project, item = world
    monkeypatch.setattr(settings, "smtp_host", "")
    _row_relay(db)
    key = f"{project.key}-{item.number}"

    await mail_service.send_ack(
        db, item_id=item.id, email="cass@vip.example.com", name="Cass",
        item_key=key, title=item.title,
    )

    # A punctuation-free slice of the default wording: the html part escapes
    # the apostrophe in "We'll" to `&#x27;` (RADD-967's "nothing survives as
    # markup" rule applying to the DEFAULT template exactly like a custom one),
    # so an exact-string check there would be pinning HTML escaping, not the
    # substitution this test is actually about.
    expected = f"tracked as {key}"
    sent = relay.sent[-1]
    assert expected in sent.get_body(("plain",)).get_content()
    assert expected in sent.get_body(("html",)).get_content()
    assert settings.mail_ack_body.replace("{{key}}", key) in sent.get_body(("plain",)).get_content()


async def test_an_explicitly_blank_ack_override_also_falls_back(
    db, world, relay, no_senders, monkeypatch
):
    """An admin who saves an empty template is a real row, not a missing one —
    the cascade's own "no row" fallback would not catch this; `send_ack` checks
    blankness itself."""
    _agent, project, item = world
    monkeypatch.setattr(settings, "smtp_host", "")
    _row_relay(db)
    key = f"{project.key}-{item.number}"
    await settings_service.set_value(
        db, SettingKey.MAIL_ACK_BODY, SettingScope.INSTANCE, None, "   "
    )
    await db.flush()

    await mail_service.send_ack(
        db, item_id=item.id, email="cass@vip.example.com", name="Cass",
        item_key=key, title=item.title,
    )

    expected = settings.mail_ack_body.replace("{{key}}", key)
    assert expected in relay.sent[-1].get_body(("plain",)).get_content()


async def test_a_custom_ack_template_changes_both_parts(
    db, world, relay, no_senders, monkeypatch
):
    """Editing Settings → Email's ack template changes the NEXT ack sent — text
    and html both, every offered token substituted."""
    _agent, project, item = world
    monkeypatch.setattr(settings, "smtp_host", "")
    _row_relay(db)
    key = f"{project.key}-{item.number}"
    await settings_service.set_value(
        db, SettingKey.MAIL_ACK_BODY, SettingScope.INSTANCE, None,
        "Hi {{requester_name}}, {{title}} is tracked as {{key}}. Track it: {{link}}",
    )
    await db.flush()

    await mail_service.send_ack(
        db, item_id=item.id, email="cass@vip.example.com", name="Cass Customer",
        item_key=key, title=item.title,
    )

    expected = (
        f"Hi Cass Customer, {item.title} is tracked as {key}. "
        f"Track it: {BASE_URL}/issues/{key}"
    )
    sent = relay.sent[-1]
    assert expected in sent.get_body(("plain",)).get_content()
    assert expected in sent.get_body(("html",)).get_content()


async def test_an_unknown_ack_token_stays_verbatim(db, world, relay, no_senders, monkeypatch):
    """Same failure mode as `canned.render.render_canned`: a token nobody
    registered is not an error, it is left exactly as written so the admin can
    see and fix the typo."""
    _agent, project, item = world
    monkeypatch.setattr(settings, "smtp_host", "")
    _row_relay(db)
    key = f"{project.key}-{item.number}"
    await settings_service.set_value(
        db, SettingKey.MAIL_ACK_BODY, SettingScope.INSTANCE, None,
        "Ticket {{key}}, ref {{bogus_token}}.",
    )
    await db.flush()

    await mail_service.send_ack(
        db, item_id=item.id, email="cass@vip.example.com", name="Cass",
        item_key=key, title=item.title,
    )

    expected = f"Ticket {key}, ref " + "{{bogus_token}}."
    assert expected in relay.sent[-1].get_body(("plain",)).get_content()
