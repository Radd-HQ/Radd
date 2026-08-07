"""Inbound mail: threading, idempotency and the loop guards (RADD-951 wave).

The acceptance criteria for this feature are almost entirely about things that
fail SILENTLY and LATE — a reply that opens a duplicate ticket, a retry that
becomes a second one, an autoresponder that runs until someone notices. None of
them raise, so none of them are caught by anything except a test that walks the
path.

The pure halves (candidate extraction, quote stripping, HTML, loop verdicts) are
tested on fixture strings; the threading and dedup halves go through a real
session, because the invariant is about what the WRITE PATH stored.
"""

import uuid
from email.message import EmailMessage

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.mailintake import intake, loops, parsing, quoting, threading
from radd.modules.mailintake.html_body import html_to_text
from radd.modules.mailintake.models import MailMessage
from radd.modules.mailintake.types import MailDirection
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
async def world(db):
    suffix = uuid.uuid4().hex[:8]
    actor = User(
        email=f"mt-{suffix}@example.com", name="Mail", instance_role=InstanceRole.ADMIN.value
    )
    db.add(actor)
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"MT{suffix[:4].upper()}", name="Mail threading")
    )
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="An existing ticket"), actor
    )
    return actor, project, item


def raw_message(
    *,
    subject="Hello",
    sender="Jane <jane@example.com>",
    body="Some text",
    message_id="<m1@example.com>",
    in_reply_to=None,
    references=None,
    auto_submitted=None,
    html=None,
    attachments=(),
) -> bytes:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = "help@radd-hq.com"
    if message_id:
        message["Message-ID"] = message_id
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references
    if auto_submitted:
        message["Auto-Submitted"] = auto_submitted
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    for name, content_type, payload in attachments:
        maintype, _, subtype = content_type.partition("/")
        message.add_attachment(payload, maintype=maintype, subtype=subtype, filename=name)
    return message.as_bytes()


async def _accept(db, raw: bytes, project_key: str, **kwargs):
    return await intake.accept(
        db,
        parsing.parse_email(raw),
        raw=raw,
        default_project_key=project_key,
        own_addresses=kwargs.pop("own_addresses", {"radd@radd-hq.com"}),
        **kwargs,
    )


# --- candidate extraction (pure) -------------------------------------------------


def test_in_reply_to_is_tried_before_references():
    assert threading.thread_candidates("<direct@x>", "<old@x> <newer@x>") == [
        "<direct@x>",
        "<newer@x>",
        "<old@x>",
    ]


def test_references_is_walked_newest_first():
    """The chain runs oldest → newest, and the newest ancestor is the most
    specific answer — a long thread whose early messages were about something
    else must resolve to the recent one."""
    assert threading.thread_candidates(None, "<a@x> <b@x> <c@x>") == ["<c@x>", "<b@x>", "<a@x>"]


@pytest.mark.parametrize(
    "value, expected",
    [
        ("<a@x>,\n <b@x>", ["<a@x>", "<b@x>"]),          # folded and comma-separated
        ("junk <a@x> more junk", ["<a@x>"]),              # clients add commentary
        ("<a@x> <a@x>", ["<a@x>"]),                       # deduped
        ("", []),
        (None, []),
        ("no brackets here", []),
    ],
)
def test_message_id_extraction_survives_real_clients(value, expected):
    assert threading.parse_message_ids(value) == expected


# --- threading through the store -------------------------------------------------


async def test_a_reply_threads_by_in_reply_to(db, world):
    _, project, item = world
    await threading.record(
        db,
        message_id="<sent-1@radd>",
        item_id=item.id,
        direction=MailDirection.OUTBOUND,
        subject="An existing ticket",
    )
    outcome = await _accept(
        db,
        raw_message(subject="Re: whatever", in_reply_to="<sent-1@radd>", message_id="<r1@ext>"),
        project.key,
    )
    assert outcome.result is intake.Result.APPENDED
    assert outcome.item_id == item.id


async def test_a_reply_threads_by_references_when_in_reply_to_is_stale(db, world):
    """A stale In-Reply-To plus a good References entry is what a forwarded or
    list-relayed reply actually looks like."""
    _, project, item = world
    await threading.record(
        db, message_id="<sent-2@radd>", item_id=item.id, direction=MailDirection.OUTBOUND
    )
    outcome = await _accept(
        db,
        raw_message(
            in_reply_to="<never-seen@elsewhere>",
            references="<sent-2@radd> <also-unknown@x>",
            message_id="<r2@ext>",
        ),
        project.key,
    )
    assert outcome.result is intake.Result.APPENDED
    assert outcome.item_id == item.id


async def test_headers_beat_a_subject_key_naming_a_different_issue(db, world):
    """The key is text a human can edit and a mailing list can mangle; the
    headers are what the client generated. When they disagree, trust the client."""
    actor, project, item = world
    other = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Some other ticket"), actor
    )
    other_key = f"{project.key}-{other.number}"
    await threading.record(
        db, message_id="<sent-3@radd>", item_id=item.id, direction=MailDirection.OUTBOUND
    )
    outcome = await _accept(
        db,
        raw_message(
            subject=f"Re: [{other_key}] confusing",
            in_reply_to="<sent-3@radd>",
            message_id="<r3@ext>",
        ),
        project.key,
    )
    assert outcome.item_id == item.id


async def test_the_subject_key_still_works_as_a_last_resort(db, world):
    _, project, item = world
    key = f"{project.key}-{item.number}"
    outcome = await _accept(
        db, raw_message(subject=f"Re: [{key}] hello", message_id="<r4@ext>"), project.key
    )
    assert outcome.result is intake.Result.APPENDED
    assert outcome.item_id == item.id


async def test_a_message_matching_nothing_opens_exactly_one_issue(db, world):
    _, project, _ = world
    outcome = await _accept(
        db, raw_message(subject="Brand new problem", message_id="<n1@ext>"), project.key
    )
    assert outcome.result is intake.Result.CREATED
    assert outcome.item_key


async def test_an_inbound_message_is_recorded_so_replies_to_IT_thread(db, world):
    """The reply-to-a-reply case. Without recording inbound ids the second reply
    falls back to the subject key."""
    _, project, _ = world
    first = await _accept(db, raw_message(message_id="<in-1@ext>"), project.key)
    second = await _accept(
        db,
        raw_message(in_reply_to="<in-1@ext>", message_id="<in-2@ext>", subject="Re: Hello"),
        project.key,
    )
    assert second.result is intake.Result.APPENDED
    assert second.item_id == first.item_id


# --- idempotency -----------------------------------------------------------------


async def test_the_same_message_id_twice_is_one_issue_and_a_duplicate(db, world):
    """Acceptance criterion 4. Cloudflare retries on timeout and every push
    provider is at-least-once, so this is one ticket versus two."""
    _, project, _ = world
    raw = raw_message(subject="Please help", message_id="<dupe@ext>")
    first = await _accept(db, raw, project.key)
    second = await _accept(db, raw, project.key)
    assert first.result is intake.Result.CREATED
    assert second.result is intake.Result.DUPLICATE
    rows = await db.execute(
        select(MailMessage).where(MailMessage.message_id == "<dupe@ext>")
    )
    assert len(list(rows.scalars())) == 1


async def test_a_message_with_no_id_is_taken_rather_than_dropped(db, world):
    """Nothing to dedup on. A duplicate ticket is recoverable; a silently
    dropped customer message is not."""
    _, project, _ = world
    outcome = await _accept(db, raw_message(message_id=None), project.key)
    assert outcome.result is intake.Result.CREATED


# --- loop prevention -------------------------------------------------------------


@pytest.mark.parametrize("marker", ["auto-replied", "auto-generated", "auto-notified"])
async def test_an_autoresponder_creates_nothing(db, world, marker):
    _, project, _ = world
    outcome = await _accept(
        db, raw_message(auto_submitted=marker, message_id=f"<auto-{marker}@ext>"), project.key
    )
    assert outcome.result is intake.Result.IGNORED


async def test_auto_submitted_no_is_a_human_and_is_accepted(db, world):
    """RFC 3834's value meaning a person sent it. Treating any marker as a robot
    would drop real mail."""
    _, project, _ = world
    outcome = await _accept(
        db, raw_message(auto_submitted="no", message_id="<human@ext>"), project.key
    )
    assert outcome.result is intake.Result.CREATED


async def test_mail_from_our_own_address_creates_nothing(db, world):
    _, project, _ = world
    outcome = await _accept(
        db,
        raw_message(sender="Radd <radd@radd-hq.com>", message_id="<self@radd>"),
        project.key,
    )
    assert outcome.result is intake.Result.IGNORED


async def test_a_list_address_is_not_treated_as_a_loop(db, world):
    """`Precedence: bulk` and `List-Id` are deliberately not triggers — plenty of
    legitimate ticket traffic comes from list addresses."""
    _, project, _ = world
    outcome = await _accept(
        db, raw_message(sender="team@lists.example.com", message_id="<list@ext>"), project.key
    )
    assert outcome.result is intake.Result.CREATED


def test_the_rate_limiter_stops_a_runaway_sender():
    limiter = loops.RateLimiter(limit=3, window=60.0)
    assert [limiter.allow("bot@x.com", now=0.0) for _ in range(4)] == [True, True, True, False]
    # …and a different sender is unaffected.
    assert limiter.allow("human@x.com", now=0.0)
    # …and it recovers once the window passes.
    assert limiter.allow("bot@x.com", now=61.0)


# --- parsing (pure) --------------------------------------------------------------


def test_an_html_only_message_produces_a_readable_body():
    """Outlook, phones and every marketing system send these; taking plain and
    stopping turned each one into a blank ticket."""
    message = EmailMessage()
    message["Subject"] = "HTML only"
    message["From"] = "a@b.com"
    message.set_content("<p>Hello <b>there</b></p><p>Second line</p>", subtype="html")
    plan = parsing.parse_email(message.as_bytes())
    assert "Hello there" in plan.body and "Second line" in plan.body
    assert plan.html_derived is True


def test_html_conversion_keeps_no_markup_at_all():
    """Stripping rather than sanitising: there is no allow-list to get wrong."""
    text = html_to_text(
        '<div onclick="steal()">Hi<script>alert(1)</script>'
        '<style>body{}</style><a href="javascript:evil()">click</a></div>'
    )
    assert "<" not in text and "script" not in text.lower()
    assert "javascript:" not in text
    assert "Hi" in text


def test_html_keeps_safe_links_and_drops_unsafe_schemes():
    assert "[docs](https://example.com)" in html_to_text('<a href="https://example.com">docs</a>')
    assert "https://" not in html_to_text('<a href="data:text/html,x">x</a>')


def test_plain_text_wins_over_html_when_both_are_present():
    raw = raw_message(body="the plain one", html="<p>the html one</p>")
    assert parsing.parse_email(raw).body == "the plain one"


@pytest.mark.parametrize(
    "body, expected",
    [
        ("My answer.\n\nOn Tue, Bob wrote:\n> old\n> older", "My answer."),
        ("My answer.\n\n> quoted\n> more", "My answer."),
        ("My answer.\n-- \nSignature", "My answer."),
        ("Le 3 mai, Bob a écrit :\n> vieux", "Le 3 mai, Bob a écrit :\n> vieux"),
        ("No quoting at all.", "No quoting at all."),
    ],
)
def test_quote_stripping_is_conservative(body, expected):
    """Over-stripping deletes the reply, which is far worse than a comment
    carrying some quoted text. The French case is all-quotation and therefore
    kept whole — never return nothing."""
    assert quoting.strip_quotes(body) == expected


async def test_attachments_become_item_attachments(db, world, tmp_path):
    from radd.modules.attachments import hosts
    from radd.modules.attachments.schemas import StorageHostCreate
    from radd.modules.attachments.types import DeliveryMode, StorageHostType

    await hosts.create_host(
        db,
        StorageHostCreate(
            name=f"mail-{uuid.uuid4().hex[:6]}",
            host_type=StorageHostType.FILESYSTEM,
            root_dir=str(tmp_path / "store"),
            delivery_mode=DeliveryMode.PROXY,
            is_default=True,
        ),
    )
    _, project, _ = world
    raw = raw_message(
        subject="With files",
        message_id="<att@ext>",
        attachments=[
            ("notes.txt", "text/plain", b"hello"),
            ("data.bin", "application/octet-stream", b"\x00\x01"),
        ],
    )
    assert len(parsing.parse_email(raw).attachments) == 2
    outcome = await _accept(db, raw, project.key)
    assert outcome.result is intake.Result.CREATED

    from radd.modules.attachments import service as attachments_service

    stored = await attachments_service.list_for_item(db, outcome.item_id)
    assert {row.filename for row in stored} == {"notes.txt", "data.bin"}
