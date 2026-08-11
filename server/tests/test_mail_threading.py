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
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.mailintake import intake, loops, parsing, quoting, registry, threading
from radd.modules.mailintake.html_body import html_to_text
from radd.modules.mailintake.models import MailMessage, MailSender, MailSource
from radd.modules.mailintake.types import MailDirection, MailSenderKind, MailSourceKind
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
    to="help@radd-hq.com",
    cc=None,
    auth_results=None,
) -> bytes:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to
    if cc:
        message["Cc"] = cc
    if message_id:
        message["Message-ID"] = message_id
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references
    if auto_submitted:
        message["Auto-Submitted"] = auto_submitted
    # One or several `Authentication-Results` headers — the MX's own SPF/DKIM/
    # DMARC stamp (RADD-1032).
    for value in [auth_results] if isinstance(auth_results, str) else (auth_results or ()):
        message["Authentication-Results"] = value
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
        # The desk's own address is in the set, as `registry.own_addresses`
        # builds it from the source rows in production — RADD-980 reads it to
        # decide which To/Cc addresses are external people rather than us.
        own_addresses=kwargs.pop("own_addresses", {"radd@radd-hq.com", "help@radd-hq.com"}),
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


async def test_the_subject_key_still_works_as_a_last_resort_for_someone_on_the_thread(db, world):
    """The fallback for a client that drops In-Reply-To and References — still
    there, now for the people the conversation belongs to (RADD-981). Here: an
    address already recorded as a contact on the item."""
    from radd.modules.mailintake import service as mail_service

    _, project, item = world
    key = f"{project.key}-{item.number}"
    await mail_service.upsert_contact(db, item.id, email="jane@example.com", name="Jane")
    outcome = await _accept(
        db, raw_message(subject=f"Re: [{key}] hello", message_id="<r4@ext>"), project.key
    )
    assert outcome.result is intake.Result.APPENDED
    assert outcome.item_id == item.id


async def test_a_colleague_may_thread_by_subject_key_on_any_issue(db, world):
    """Deliberately broad: an agent forwarding a ticket, or replying from a
    client that mangled the headers, must not be told their mail opened a
    duplicate. What the gate excludes is the account an unknown SENDER is
    provisioned as, not staff."""
    actor, project, item = world
    key = f"{project.key}-{item.number}"
    outcome = await _accept(
        db,
        raw_message(sender=f"Agent <{actor.email}>", subject=f"Re: [{key}] hello",
                    message_id="<r4b@ext>"),
        project.key,
    )
    assert outcome.result is intake.Result.APPENDED
    assert outcome.item_id == item.id


async def test_a_stranger_naming_an_issue_key_opens_a_new_one_instead(db, world):
    """RADD-981. `[PROJ-412]` is a guessable string in a text field — keys are
    sequential — and the subject key was the ONLY check on it. So a stranger who
    typed one wrote into somebody else's ticket, and the outbound consumer then
    mailed their words to that ticket's requester.

    Refused, not dropped: a stranger with the wrong subject line is still a
    person asking for help, so the message becomes a new routed issue.
    """
    _, project, item = world
    key = f"{project.key}-{item.number}"
    outcome = await _accept(
        db,
        raw_message(
            sender="Mallory <mallory@elsewhere.example>",
            subject=f"Re: [{key}] give me the details",
            message_id="<snoop@ext>",
        ),
        project.key,
    )
    assert outcome.result is intake.Result.CREATED
    assert outcome.item_id != item.id


async def test_a_stripped_key_still_threads_the_contact_by_header(db, world):
    """The gate touches the SUBJECT-KEY leg alone. An In-Reply-To names an id
    Radd generated and told exactly one person, so holding it IS the evidence —
    and it is what a real client sends when the human edits the subject."""
    _, project, item = world
    await threading.record(
        db, message_id="<sent-9@radd>", item_id=item.id, direction=MailDirection.OUTBOUND
    )
    outcome = await _accept(
        db,
        raw_message(
            sender="Cass <cass@vip.example.com>",
            subject="my printer, again",  # no key at all
            in_reply_to="<sent-9@radd>",
            message_id="<r4c@ext>",
        ),
        project.key,
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


# --- attribution (RADD-981) ------------------------------------------------------


async def _comments_on(db, item_id):
    from radd.modules.comments import service as comments_service

    return await comments_service.public_comments_for_item(db, item_id)


async def test_an_agents_mailed_reply_is_their_own_comment(db, world):
    """Every inbound reply used to be a SYSTEM comment with the sender named in
    the body. For a customer with no account that is the only honest answer; for
    a colleague replying to a notification it was wrong in four places at once —
    the issue read as if a robot had spoken, the outbound consumer's SYSTEM gate
    refused to relay it to the requester, the SLA response timer skipped it as a
    non-answer, and notify (which excludes the ACTOR) notified the agent of
    their own comment while nobody else's exclusion applied."""
    actor, project, item = world
    await threading.record(
        db, message_id="<sent-a1@radd>", item_id=item.id, direction=MailDirection.OUTBOUND
    )
    await _accept(
        db,
        raw_message(
            sender=f"Ada Agent <{actor.email}>",
            body="Engineer dispatched.",
            in_reply_to="<sent-a1@radd>",
            message_id="<agent-reply@ext>",
        ),
        project.key,
    )

    [comment] = await _comments_on(db, item.id)
    assert comment.author_id == actor.id, "attributed to the person, not the system"
    assert comment.body == "Engineer dispatched."
    assert "Email reply from" not in comment.body


async def test_a_customers_mailed_reply_stays_a_system_comment(db, world):
    """The other half, and the reason the prefix survives: an unknown sender is
    provisioned as a `UserSource.EMAIL` requester (RADD-828), and attributing a
    forgeable `From:` to that account would make the header an identity."""
    from radd.modules.automations.types import SYSTEM_ACTOR_ID

    _, project, item = world
    await threading.record(
        db, message_id="<sent-a2@radd>", item_id=item.id, direction=MailDirection.OUTBOUND
    )
    await _accept(
        db,
        raw_message(
            sender="Cass <cass@vip.example.com>",
            body="Still broken.",
            in_reply_to="<sent-a2@radd>",
            message_id="<cust-reply@ext>",
        ),
        project.key,
    )

    [comment] = await _comments_on(db, item.id)
    assert comment.author_id == SYSTEM_ACTOR_ID
    assert comment.body.startswith("Email reply from Cass <cass@vip.example.com>:")


async def test_attribution_is_not_authorisation(db, world):
    """`From:` is a claim this module treats as forgeable everywhere else, so the
    comment goes through the ordinary write door and is checked against that
    person's own `comment.write`. Someone who cannot write there falls back to
    SYSTEM: the message still lands, and nothing was granted on a header."""
    from radd.modules.auth.types import InstanceRole, UserSource
    from radd.modules.automations.types import SYSTEM_ACTOR_ID

    _, project, item = world
    outsider = User(
        email=f"nobody-{uuid.uuid4().hex[:8]}@example.com",
        name="No Permissions",
        instance_role=InstanceRole.MEMBER.value,
        source=UserSource.LOCAL.value,
    )
    db.add(outsider)
    await db.flush()
    await threading.record(
        db, message_id="<sent-a3@radd>", item_id=item.id, direction=MailDirection.OUTBOUND
    )
    await _accept(
        db,
        raw_message(
            sender=f"Nobody <{outsider.email}>",
            body="let me in",
            in_reply_to="<sent-a3@radd>",
            message_id="<outsider@ext>",
        ),
        project.key,
    )

    [comment] = await _comments_on(db, item.id)
    assert comment.author_id == SYSTEM_ACTOR_ID
    assert "Email reply from" in comment.body


# --- sender authentication + the subject-key gate (RADD-1032) --------------------


def _source_with_trust(db, project, authserv):
    row = MailSource(
        name=f"box-{uuid.uuid4().hex[:6]}", kind=MailSourceKind.IMAP.value,
        address="help@radd-hq.com", host="imap.test", username="help@radd-hq.com",
        secret="pw", default_project_id=project.id, trusted_authserv_id=authserv,
    )
    db.add(row)
    return row


def test_parse_auth_results_reads_only_the_trusted_block():
    """Several hosts stamp their own; only the authserv-id the source trusts is
    read. A malformed/absent verdict is None (absent), a present block naming no
    method is `{}` (present but empty) — both unverified, but only None is ABSENT."""
    headers = (
        "mx.radd-hq.com; dkim=pass header.d=x.com; spf=pass smtp.mailfrom=x.com; dmarc=pass",
        "other.relay.net; dkim=fail",
    )
    assert parsing.parse_auth_results(headers, "mx.radd-hq.com") == {
        "dkim": "pass", "spf": "pass", "dmarc": "pass"
    }
    assert parsing.parse_auth_results(headers, "other.relay.net") == {"dkim": "fail"}
    # An authserv-id we do not trust is ignored entirely, even though it is present.
    assert parsing.parse_auth_results(headers, "not-configured") is None
    # authserv-id may carry a version, and is compared case-insensitively.
    assert parsing.parse_auth_results(("MX.Radd-HQ.com 1; spf=Fail",), "mx.radd-hq.com") == {
        "spf": "fail"
    }
    assert parsing.parse_auth_results((), "mx.radd-hq.com") is None  # absent
    assert parsing.parse_auth_results(("mx.radd-hq.com; none",), "mx.radd-hq.com") == {}  # empty


@pytest.mark.parametrize(
    "results, demoted",
    [
        ("mx.radd-hq.com; dkim=pass; spf=pass; dmarc=pass", False),
        ("mx.radd-hq.com; dkim=fail; spf=fail; dmarc=fail", True),   # forged
        ("mx.radd-hq.com; spf=softfail", True),                       # any fail-like
        ("mx.radd-hq.com; none", True),                               # present, no pass
        (None, True),                                                 # absent when required
    ],
)
def test_the_verdict_decides_demotion(results, demoted):
    plan = parsing.parse_email(raw_message(auth_results=results, message_id="<v@ext>"))
    assert intake._check_sender_auth(plan, "mx.radd-hq.com").demoted is demoted
    # No trust configured is ALWAYS the None (undecided) verdict — today's behaviour.
    assert intake._check_sender_auth(plan, None).verified is None


async def test_a_forged_from_failing_auth_is_demoted_to_system_with_a_note(db, world):
    """RADD-1032 layer 1. A forged staff `From:` that fails the trusted gateway's
    verdict is recorded as received but attributed to SYSTEM — never to the
    account it forged — so it cannot speak as that person, stop the SLA clock, or
    be relayed to the requester. The body survives; a warning leads it."""
    from radd.modules.automations.types import SYSTEM_ACTOR_ID

    actor, project, item = world
    source = _source_with_trust(db, project, "mx.radd-hq.com")
    await db.flush()
    await threading.record(
        db, message_id="<sent-auth@radd>", item_id=item.id, direction=MailDirection.OUTBOUND
    )
    await _accept(
        db,
        raw_message(
            sender=f"Ada Agent <{actor.email}>", body="Approve the refund.",
            in_reply_to="<sent-auth@radd>", message_id="<forged@ext>",
            auth_results="mx.radd-hq.com; dkim=fail; spf=fail; dmarc=fail",
        ),
        project.key,
        source_id=source.id,
    )

    [comment] = await _comments_on(db, item.id)
    assert comment.author_id == SYSTEM_ACTOR_ID, "demoted, not attributed to the forged account"
    assert "Unverified sender" in comment.body
    assert "Approve the refund." in comment.body


async def test_a_passing_auth_verdict_keeps_the_real_author(db, world):
    """The other half: a genuine staff reply the gateway vouched for is still
    that person's own comment — the demotion must not tax the legitimate path."""
    actor, project, item = world
    source = _source_with_trust(db, project, "mx.radd-hq.com")
    await db.flush()
    await threading.record(
        db, message_id="<sent-ok@radd>", item_id=item.id, direction=MailDirection.OUTBOUND
    )
    await _accept(
        db,
        raw_message(
            sender=f"Ada Agent <{actor.email}>", body="Engineer dispatched.",
            in_reply_to="<sent-ok@radd>", message_id="<genuine@ext>",
            auth_results="mx.radd-hq.com; dkim=pass; spf=pass; dmarc=pass",
        ),
        project.key,
        source_id=source.id,
    )

    [comment] = await _comments_on(db, item.id)
    assert comment.author_id == actor.id
    assert "Unverified sender" not in comment.body


async def test_without_a_trusted_authserv_nothing_is_demoted(db, world):
    """The no-config pin: existing installs behave EXACTLY as today. Even a header
    screaming `dkim=fail` is ignored when the source trusts no authserv-id — the
    admin has not opted in, so `From:` is taken at face value as before."""
    actor, project, item = world
    await threading.record(
        db, message_id="<sent-nc@radd>", item_id=item.id, direction=MailDirection.OUTBOUND
    )
    await _accept(
        db,
        raw_message(
            sender=f"Ada Agent <{actor.email}>", body="Genuine reply.",
            in_reply_to="<sent-nc@radd>", message_id="<nc@ext>",
            auth_results="mx.radd-hq.com; dkim=fail",  # present, but nobody trusts it
        ),
        project.key,  # no source_id → no trusted authserv
    )

    [comment] = await _comments_on(db, item.id)
    assert comment.author_id == actor.id, "no trust configured → today's behaviour"


async def test_a_demoted_new_issue_names_no_reporter(db, world):
    """A demoted CREATE: the reporter is only a mailback claim, but pinning it to
    the account a forged `From:` names still asserts an identity — so a demoted
    issue names no reporter and its description carries the warning."""
    actor, project, _ = world
    source = _source_with_trust(db, project, "mx.radd-hq.com")
    await db.flush()
    outcome = await _accept(
        db,
        raw_message(
            sender=f"Ada Agent <{actor.email}>", subject="Wire the money", body="Now.",
            message_id="<forge-new@ext>", auth_results="mx.radd-hq.com; dkim=fail",
        ),
        project.key,
        source_id=source.id,
    )
    item = await items_service.require_item(db, outcome.item_id)
    assert item.reporter_id is None
    assert "Unverified sender" in item.description


async def test_a_real_member_who_cannot_write_here_is_a_stranger_to_the_thread(db, world):
    """RADD-1032 layer 2. The subject-key leg used to admit ANY active real
    account instance-wide — so a member with no grant on THIS project could type
    into every ticket whose sequential key they guessed. It now needs
    `comment.write` on the item's own project; a stranger's key opens a NEW issue
    instead (refused, not dropped)."""
    from radd.modules.auth.types import InstanceRole, UserSource

    _, project, item = world
    key = f"{project.key}-{item.number}"
    member = User(
        email=f"m-{uuid.uuid4().hex[:8]}@example.com", name="No Grant",
        instance_role=InstanceRole.MEMBER.value, source=UserSource.LOCAL.value,
    )
    db.add(member)
    await db.flush()
    outcome = await _accept(
        db,
        raw_message(
            sender=f"NG <{member.email}>",
            subject=f"Re: [{key}] give me the details", message_id="<memstranger@ext>",
        ),
        project.key,
    )
    assert outcome.result is intake.Result.CREATED
    assert outcome.item_id != item.id


# --- contacts (RADD-980) ---------------------------------------------------------


async def _contacts(db, item_id) -> dict[str, bool]:
    """`{email: is_primary}` for an item — the whole shape of the change."""
    from radd.modules.mailintake import service as mail_service

    return {c.email: c.is_primary for c in await mail_service.contacts_for_item(db, item_id)}


async def test_the_cc_line_becomes_contacts_and_the_sender_is_the_primary(db, world):
    """`extract_recipients` has harvested To/Cc since RADD-958 and only ROUTING
    read it. So a customer who copied two colleagues raised a ticket that knew
    about one of the three, and answering it reached one of the three."""
    _, project, _ = world
    outcome = await _accept(
        db,
        raw_message(
            sender="Cass <cass@vip.example.com>",
            cc="Bill <bill@vip.example.com>, ops@vip.example.com",
            message_id="<cc1@ext>",
        ),
        project.key,
    )

    assert await _contacts(db, outcome.item_id) == {
        "cass@vip.example.com": True,  # she wrote it
        "bill@vip.example.com": False,
        "ops@vip.example.com": False,
    }


async def test_a_cc_that_is_a_real_user_is_a_colleague_not_a_contact(db, world):
    """A copied-in staff member is reached by notify, off the rows that decide
    their inbox. Recording them here as well is the duplicate fan-out RADD-968
    deleted — they would get the comment twice, once addressed "you contacted
    us". Our OWN desk address is excluded for the adjacent reason: we are not a
    party to the conversation."""
    actor, project, _ = world
    outcome = await _accept(
        db,
        raw_message(
            sender="Cass <cass@vip.example.com>",
            to=f"help@radd-hq.com, {actor.email}",
            message_id="<cc2@ext>",
        ),
        project.key,
    )

    assert await _contacts(db, outcome.item_id) == {"cass@vip.example.com": True}


async def test_our_own_plus_addressed_alias_is_not_an_external_requester(db, world):
    """`support+td@` is spec 62's routing convention, so it is expected traffic
    on the To line — but `own_addresses` holds the MAILBOX. A literal comparison
    files the desk's own alias as a requester, shows it in the issue rail, and
    mails it every reply."""
    _, project, _ = world
    outcome = await _accept(
        db,
        raw_message(
            sender="Cass <cass@vip.example.com>",
            to=f"help+{project.key.lower()}@radd-hq.com",
            message_id="<plus1@ext>",
        ),
        project.key,
    )

    assert await _contacts(db, outcome.item_id) == {"cass@vip.example.com": True}


async def test_a_second_sender_on_the_thread_is_recorded(db, world):
    """The bug this replaces was a guard that could not fire: `_touch_contact`
    asked `_sender_user(...) is None`, and that function PROVISIONS an account
    for an unknown address — so it was never None, and a colleague answering on
    the customer's behalf was never recorded at all."""
    _, project, _ = world
    first = await _accept(
        db, raw_message(sender="Cass <cass@vip.example.com>", message_id="<t1@ext>"), project.key
    )
    await _accept(
        db,
        raw_message(
            sender="Bill <bill@vip.example.com>",
            subject="Re: Hello",
            in_reply_to="<t1@ext>",
            message_id="<t2@ext>",
        ),
        project.key,
    )

    assert await _contacts(db, first.item_id) == {
        "cass@vip.example.com": True,   # unmoved: she raised it
        "bill@vip.example.com": False,
    }


async def test_a_reply_advances_only_the_sender_s_own_last_message(db, world):
    """`last_message_id` used to be advanced on whichever single contact the item
    had, whoever had actually written."""
    from radd.modules.mailintake import service as mail_service

    _, project, _ = world
    first = await _accept(
        db, raw_message(sender="cass@vip.example.com", message_id="<l1@ext>"), project.key
    )
    await _accept(
        db,
        raw_message(
            sender="bill@vip.example.com",
            subject="Re: Hello",
            in_reply_to="<l1@ext>",
            message_id="<l2@ext>",
        ),
        project.key,
    )

    stored = {
        c.email: c.last_message_id
        for c in await mail_service.contacts_for_item(db, first.item_id)
    }
    assert stored == {"cass@vip.example.com": "<l1@ext>", "bill@vip.example.com": "<l2@ext>"}


async def test_an_agent_raised_issue_gains_its_requester_when_they_write_in(db, world):
    """An issue raised in the UI has no contact at all, so a customer's mail onto
    that thread produced a comment nobody could answer — the reply consumer plans
    nothing without a recipient. The first external person to WRITE is the
    requester, whether or not the issue was born from mail.

    Threaded on a HEADER, the way this reaches an agent-raised issue in
    practice: somebody was mailed about it (notify, or a `send_email` action),
    and the customer replied to that message.
    """
    _, project, item = world
    await threading.record(
        db,
        message_id="<told-them@radd>",
        item_id=item.id,
        direction=MailDirection.OUTBOUND,
        subject="An existing ticket",
    )
    await _accept(
        db,
        raw_message(
            sender="Cass <cass@vip.example.com>",
            subject="Re: An existing ticket",
            in_reply_to="<told-them@radd>",
            message_id="<agent1@ext>",
        ),
        project.key,
    )

    assert await _contacts(db, item.id) == {"cass@vip.example.com": True}


# --- the acknowledgement (RADD-995) ----------------------------------------------


async def test_a_recognised_user_mailing_the_desk_gets_a_receipt(db, world):
    """Caught live. A colleague signed in with Google mailed the desk, became the
    reporter of a real ticket, and heard nothing back — because the ack was
    planned on the branch that captured a `mail_contact`, and a recognised user
    never gets one. Every other part of that path worked, so there was nothing
    to notice.

    A receipt answers a MESSAGE. The two facts are independent now: this item
    has an ack and no contact.
    """
    actor, project, _ = world
    outcome = await _accept(
        db,
        raw_message(sender=f"Ada Agent <{actor.email}>", subject="my laptop", message_id="<u1@ext>"),
        project.key,
    )

    assert outcome.result is intake.Result.CREATED
    assert outcome.ack is not None
    assert outcome.ack.email == actor.email
    assert outcome.ack.item_key == outcome.item_key
    assert await _contacts(db, outcome.item_id) == {}, "a user is not a contact"


async def test_a_contact_still_gets_the_same_receipt(db, world):
    """The path that always worked, pinned beside the one that did not — the
    change must be additive, not a swap."""
    _, project, _ = world
    outcome = await _accept(
        db,
        raw_message(sender="Cass <cass@vip.example.com>", message_id="<u2@ext>"),
        project.key,
    )

    assert outcome.ack is not None and outcome.ack.email == "cass@vip.example.com"
    assert await _contacts(db, outcome.item_id) == {"cass@vip.example.com": True}


async def test_nothing_addressed_to_ourselves_is_ever_acked(db, world):
    """Two guards, and the second is the one RADD-995 had to state. The loop
    check drops our own mail before an item exists at all; `_ack_plan` refuses
    the same address independently, so widening the ack from "senders with a
    contact" to "every sender" cannot become the one path that re-opens the
    loop.
    """
    _, project, _ = world
    dropped = await _accept(
        db, raw_message(sender="Radd <radd@radd-hq.com>", message_id="<u3@ext>"), project.key
    )
    assert dropped.result is intake.Result.IGNORED and dropped.ack is None

    created = SimpleNamespace(id=uuid.uuid4(), key="MT-1", title="t")
    ours = parsing.parse_email(raw_message(sender="Radd <radd@radd-hq.com>", message_id="<u4@ext>"))
    assert intake._ack_plan(ours, created, {"radd@radd-hq.com"}) is None
    assert intake._ack_plan(ours, created, set()) is not None, "the guard, not an empty plan"

    # No `From:` at all: nowhere to send a receipt to.
    anonymous = parsing.parse_email(raw_message(sender="", message_id="<u5@ext>"))
    assert intake._ack_plan(anonymous, created, set()) is None


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


async def test_mail_from_the_sending_identity_into_the_polled_box_is_a_loop(db, world):
    """The failure the Migadu topology makes reachable: Radd sends as `agent@`,
    polls `help@`, and its own message arrives back in the box it reads.

    Driven through `registry.own_addresses` — the ONE definition since RADD-970
    deleted the env-only `loops.own_addresses` beside it. Two definitions of
    "us" is how the guard comes to fire on the webhook path and not the polled
    one, silently; so the guard is tested against the set production builds,
    from the ROWS an admin actually configured.
    """
    _, project, _ = world
    db.add(MailSource(
        name=f"in-{uuid.uuid4().hex[:6]}", kind=MailSourceKind.IMAP.value,
        address="help@radd-hq.com", username="help@radd-hq.com", host="imap.test",
    ))
    db.add(MailSender(
        name=f"out-{uuid.uuid4().hex[:6]}", kind=MailSenderKind.SMTP.value,
        host="smtp.test", from_address="Radd <agent@radd-hq.com>",
    ))
    await db.flush()

    own = await registry.own_addresses(db)
    assert {"agent@radd-hq.com", "help@radd-hq.com"} <= own

    outcome = await intake.accept(
        db,
        parsing.parse_email(
            raw_message(sender="Radd <agent@radd-hq.com>", message_id="<echo@radd>")
        ),
        raw=b"",
        default_project_key=project.key,
        own_addresses=own,
    )
    assert outcome.result is intake.Result.IGNORED


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


async def _default_host(db, tmp_path):
    from radd.modules.attachments import hosts
    from radd.modules.attachments.schemas import StorageHostCreate
    from radd.modules.attachments.types import DeliveryMode, StorageHostType

    return await hosts.create_host(
        db,
        StorageHostCreate(
            name=f"mail-{uuid.uuid4().hex[:6]}",
            host_type=StorageHostType.FILESYSTEM,
            root_dir=str(tmp_path / "store"),
            delivery_mode=DeliveryMode.PROXY,
            is_default=True,
        ),
    )


# --- raw retention (RADD-1033) ---------------------------------------------------


async def test_the_raw_message_is_retained_and_retrievable(db, world, tmp_path):
    """RADD-1033. `intake` and `quoting` both CLAIMED the raw was kept, and it was
    dropped on the floor. Now it is stored per-message through the spec-102 blob
    seam and readable back for the retention window — an over-eager quote strip or
    a capped attachment is recoverable from these bytes."""
    from radd.modules.attachments import service as attachments_service

    await _default_host(db, tmp_path)
    _, project, _ = world
    raw = raw_message(subject="keep me", message_id="<raw1@ext>", body="the original words")
    outcome = await _accept(db, raw, project.key)
    assert outcome.result is intake.Result.CREATED

    row = await db.scalar(select(MailMessage).where(MailMessage.message_id == "<raw1@ext>"))
    assert row.raw_storage_name and row.raw_size_bytes == len(raw)
    fetched = await attachments_service.read_blob(
        db, row.raw_storage_name, host_id=row.raw_host_id
    )
    assert fetched == raw


async def test_retention_off_keeps_nothing(db, world, tmp_path, monkeypatch):
    """`MAIL_RAW_RETENTION_DAYS = 0` is the privacy-conscious choice — a desk that
    must not keep customer mail at rest. Nothing is stored, and the message still
    lands."""
    await _default_host(db, tmp_path)
    monkeypatch.setattr(intake, "MAIL_RAW_RETENTION_DAYS", 0)
    _, project, _ = world
    outcome = await _accept(db, raw_message(message_id="<noretain@ext>"), project.key)
    assert outcome.result is intake.Result.CREATED
    row = await db.scalar(select(MailMessage).where(MailMessage.message_id == "<noretain@ext>"))
    assert row.raw_storage_name is None and row.raw_host_id is None


async def test_the_raw_download_is_gated_and_serves_the_bytes(db, world, tmp_path):
    """Reads sit behind the item's read gate — the same door its attachments use.
    An actor who can read the ticket gets the exact bytes back."""
    from radd.modules.mailintake.router import mail_message_raw

    await _default_host(db, tmp_path)
    actor, project, _ = world
    raw = raw_message(subject="download me", message_id="<dl1@ext>", body="original words")
    await _accept(db, raw, project.key)
    row = await db.scalar(select(MailMessage).where(MailMessage.message_id == "<dl1@ext>"))
    resp = await mail_message_raw(row.id, db, actor)
    assert resp.body == raw
    assert resp.media_type == "message/rfc822"


async def test_the_raw_download_404s_when_nothing_was_retained(db, world, tmp_path, monkeypatch):
    """Unknown id and retention-kept-nothing are the same 404 — a probe learns
    nothing about which."""
    from radd.exceptions import NotFoundError
    from radd.modules.mailintake.router import mail_message_raw

    await _default_host(db, tmp_path)
    monkeypatch.setattr(intake, "MAIL_RAW_RETENTION_DAYS", 0)
    actor, project, _ = world
    await _accept(db, raw_message(message_id="<none@ext>"), project.key)
    row = await db.scalar(select(MailMessage).where(MailMessage.message_id == "<none@ext>"))
    with pytest.raises(NotFoundError):
        await mail_message_raw(row.id, db, actor)


# --- capped attachments leave a receipt (RADD-1035a) -----------------------------


def test_a_cap_reports_how_many_attachments_it_dropped(monkeypatch):
    """The count is reported by pure parsing; `intake` turns it into a note."""
    monkeypatch.setattr(parsing, "MAX_ATTACHMENTS", 2)
    raw = raw_message(
        subject="lots",
        message_id="<cap@ext>",
        attachments=[(f"f{i}.txt", "text/plain", b"x") for i in range(5)],
    )
    plan = parsing.parse_email(raw)
    assert len(plan.attachments) == 2 and plan.attachments_dropped == 3


async def test_a_capped_message_leaves_a_note_naming_the_dropped_count(
    db, world, tmp_path, monkeypatch
):
    """A silent drop is exactly what the cap must not be — someone whose screenshot
    vanished has no way to know. One SYSTEM note on the item names the count."""
    await _default_host(db, tmp_path)
    monkeypatch.setattr(parsing, "MAX_ATTACHMENTS", 2)
    _, project, _ = world
    raw = raw_message(
        subject="lots of files",
        message_id="<capnote@ext>",
        attachments=[(f"f{i}.txt", "text/plain", b"x") for i in range(5)],
    )
    outcome = await _accept(db, raw, project.key)
    [note] = await _comments_on(db, outcome.item_id)
    assert "3 attachment(s)" in note.body and "not stored" in note.body


# --- account lookups are batched (RADD-1042) -------------------------------------


async def test_capturing_contacts_batches_the_account_lookups(db, world, monkeypatch):
    """The recipient sweep used to run a `get_user_by_email` per CC — a query per
    recipient on the hot path of every first message. It is now ONE
    `WHERE email IN (...)`, byte-identical behaviour from one dict."""
    from radd.modules.auth import service as auth_service

    _, project, _ = world
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="t"), world[0]
    )
    plan = parsing.parse_email(
        raw_message(
            sender="cass@vip.example.com",
            cc="bill@vip.example.com, ops@vip.example.com",
            message_id="<batch@ext>",
        )
    )
    calls = {"batch": 0, "single": 0}
    real_batch = auth_service.users_by_emails
    real_single = auth_service.get_user_by_email

    async def spy_batch(session, emails):
        calls["batch"] += 1
        return await real_batch(session, emails)

    async def spy_single(session, email):
        calls["single"] += 1
        return await real_single(session, email)

    monkeypatch.setattr(auth_service, "users_by_emails", spy_batch)
    monkeypatch.setattr(auth_service, "get_user_by_email", spy_single)
    await intake._capture_contacts(db, item.id, plan, own_addresses={"help@radd-hq.com"})

    assert calls["batch"] == 1, "one batched lookup for sender + every recipient"
    assert calls["single"] == 0, "no per-recipient lookup survives"
