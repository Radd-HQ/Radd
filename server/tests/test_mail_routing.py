"""The routing chain: which project a new message opens in (RADD-958/961).

Two claims, and they fail in opposite directions.

**Aliases must route.** `help@` → RADD, `pipeline@` → DEV. The trap is that on
most hosts an alias delivers into a SHARED mailbox, so the IMAP connection sees
one inbox and the alias exists only in the headers — a matcher that looked at the
connection, or at the raw header text rather than the parsed address, would pass
a unit test and route everything to the default in production.

**The AI classifier must never cost a message.** A misrouted ticket is an
annoyance; a customer email dropped because a model was slow is not survivable,
and every failure path here is one a naive implementation gets wrong by raising.
"""

import uuid

import pytest
from email.message import EmailMessage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.mailintake import intake, parsing, routing
from radd.modules.mailintake.models import MailRule, MailSource
from radd.modules.mailintake.types import MailRuleType, MailSourceKind
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
    """A source with two projects to route between — `help@` and `pipeline@`."""
    suffix = uuid.uuid4().hex[:6]
    actor = User(
        email=f"mr-{suffix}@example.com", name="Route", instance_role=InstanceRole.ADMIN.value
    )
    db.add(actor)
    await db.flush()
    default = await projects_service.create_project(
        db, ProjectCreate(key=f"RD{suffix[:4].upper()}", name="Default")
    )
    dev = await projects_service.create_project(
        db, ProjectCreate(key=f"DV{suffix[:4].upper()}", name="Dev")
    )
    source = MailSource(
        name="Migadu help",
        kind=MailSourceKind.IMAP.value,
        address="help@radd-hq.com",
        default_project_id=default.id,
    )
    db.add(source)
    await db.flush()
    return source, default, dev


def message(*, to="help@radd-hq.com", sender="Jane <jane@customer.example>", subject="Hi",
            body="the build is broken", message_id=None) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg["Message-ID"] = message_id or f"<{uuid.uuid4().hex}@x>"
    msg.set_content(body)
    return msg.as_bytes()


def _rule(source, rule_type, config, *, project=None, position=0.0, enabled=True):
    return MailRule(
        source_id=source.id,
        name=f"{rule_type}-rule",
        rule_type=rule_type,
        config=config,
        project_id=project.id if project else None,
        position=position,
        enabled=enabled,
    )


# --- alias routing --------------------------------------------------------------


async def test_an_alias_routes_to_its_own_project(db, world):
    """The headline ask: pipeline@ opens in DEV even though it shares help@'s
    mailbox."""
    source, _, dev = world
    db.add(_rule(source, MailRuleType.RECIPIENT.value, {"addresses": ["pipeline@radd-hq.com"]}, project=dev))
    await db.flush()

    plan = parsing.parse_email(message(to="pipeline@radd-hq.com"))
    decision = await routing.decide(db, plan, source_id=source.id)
    assert decision.project_id == dev.id
    assert "rule" in decision.reason


async def test_the_alias_match_reads_the_address_not_the_header_text(db, world):
    """`To: Pipeline Team <PIPELINE@radd-hq.com>` is the same alias. A substring
    match on the raw header would also fire on a display name."""
    source, _, dev = world
    db.add(_rule(source, MailRuleType.RECIPIENT.value, {"addresses": ["pipeline@radd-hq.com"]}, project=dev))
    await db.flush()

    cased = parsing.parse_email(message(to="Pipeline Team <PIPELINE@radd-hq.com>"))
    assert (await routing.decide(db, cased, source_id=source.id)).project_id == dev.id

    # A display name that merely CONTAINS the word must not match.
    decoy = parsing.parse_email(message(to="pipeline discussion <other@radd-hq.com>"))
    assert (await routing.decide(db, decoy, source_id=source.id)).project_id is None


async def test_a_message_matching_no_rule_falls_to_the_sources_default(db, world):
    source, default, dev = world
    db.add(_rule(source, MailRuleType.RECIPIENT.value, {"addresses": ["pipeline@radd-hq.com"]}, project=dev))
    await db.flush()

    plan = parsing.parse_email(message(to="help@radd-hq.com"))
    assert (await routing.decide(db, plan, source_id=source.id)).project_id is None
    # …and intake resolves that None to the source's default.
    project = await intake._target_project(db, plan, "", source.id)
    assert project.id == default.id


async def test_the_first_matching_rule_wins_by_position(db, world):
    """A message to help@ CC'd to pipeline@ matches both; order decides, which is
    why the chain is ordered and admin-editable rather than alphabetical."""
    source, default, dev = world
    db.add(_rule(source, MailRuleType.RECIPIENT.value, {"addresses": ["pipeline@radd-hq.com"]}, project=dev, position=1))
    db.add(_rule(source, MailRuleType.RECIPIENT.value, {"addresses": ["help@radd-hq.com"]}, project=default, position=2))
    await db.flush()

    msg = EmailMessage()
    msg["Subject"] = "both"; msg["From"] = "a@b.com"
    msg["To"] = "help@radd-hq.com"; msg["Cc"] = "pipeline@radd-hq.com"
    msg["Message-ID"] = "<both@x>"; msg.set_content("x")
    decision = await routing.decide(db, parsing.parse_email(msg.as_bytes()), source_id=source.id)
    assert decision.project_id == dev.id  # position 1


async def test_a_disabled_rule_is_skipped(db, world):
    source, _, dev = world
    db.add(_rule(source, MailRuleType.RECIPIENT.value, {"addresses": ["pipeline@radd-hq.com"]},
                 project=dev, enabled=False))
    await db.flush()
    plan = parsing.parse_email(message(to="pipeline@radd-hq.com"))
    assert (await routing.decide(db, plan, source_id=source.id)).project_id is None


# --- sender and subject ----------------------------------------------------------


async def test_a_whole_domain_can_be_routed(db, world):
    source, _, dev = world
    db.add(_rule(source, MailRuleType.SENDER.value, {"patterns": ["@vip.com"]}, project=dev))
    await db.flush()
    vip = parsing.parse_email(message(sender="Boss <boss@vip.com>"))
    other = parsing.parse_email(message(sender="Someone <a@notvip.com>"))
    assert (await routing.decide(db, vip, source_id=source.id)).project_id == dev.id
    assert (await routing.decide(db, other, source_id=source.id)).project_id is None


async def test_subject_matching_is_a_substring_not_a_regex(db, world):
    """Deliberately not a regex: a rule that can hang the intake path on a
    pathological pattern is not worth the expressiveness."""
    source, _, dev = world
    db.add(_rule(source, MailRuleType.SUBJECT.value, {"contains": ["[URGENT]"]}, project=dev))
    await db.flush()
    hit = parsing.parse_email(message(subject="re: [urgent] everything is down"))
    assert (await routing.decide(db, hit, source_id=source.id)).project_id == dev.id


# --- the AI classifier's failure paths -------------------------------------------


async def test_the_llm_rule_falls_through_when_ai_is_disabled(db, world):
    """The property that matters more than the classification. The ai module is
    optional and its toggle can be off; neither may cost a customer their email."""
    source, _, dev = world
    db.add(_rule(source, MailRuleType.LLM.value,
                 {"prompt": "classify", "answers": [{"answer": "dev", "project_id": str(dev.id)}]}))
    await db.flush()
    plan = parsing.parse_email(message())
    # MAIL_ROUTING is off by default, so this exercises the toggle path.
    decision = await routing.decide(db, plan, source_id=source.id)
    assert decision.project_id is None


async def test_an_llm_rule_with_no_answers_is_a_no_op(db, world):
    source, _, _ = world
    db.add(_rule(source, MailRuleType.LLM.value, {"prompt": "classify", "answers": []}))
    await db.flush()
    assert (await routing.decide(db, parsing.parse_email(message()), source_id=source.id)).project_id is None


async def test_a_rule_that_raises_is_skipped_and_the_chain_continues(db, world):
    """One broken rule must not cost the message — and must not stop a later
    rule that would have matched."""
    source, _, dev = world
    db.add(_rule(source, "not-a-real-type", {}, position=1))
    db.add(_rule(source, MailRuleType.RECIPIENT.value, {"addresses": ["help@radd-hq.com"]},
                 project=dev, position=2))
    await db.flush()
    decision = await routing.decide(db, parsing.parse_email(message()), source_id=source.id)
    assert decision.project_id == dev.id


async def test_a_source_with_no_rules_routes_nowhere_rather_than_raising(db, world):
    source, _, _ = world
    assert (await routing.decide(db, parsing.parse_email(message()), source_id=source.id)).project_id is None
    assert (await routing.decide(db, parsing.parse_email(message()), source_id=None)).project_id is None


# --- the property that makes the AI rule affordable -------------------------------


async def test_a_reply_never_reaches_the_routing_chain(db, world):
    """First message only, and it is free: threading resolves before `_create`,
    so a reply lands on its issue and no classifier ever runs. Without this the
    AI rule would re-decide the project on message four of a thread."""
    from radd.modules.items import service as items_service
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.mailintake import threading as mail_threading
    from radd.modules.mailintake.types import MailDirection

    source, default, dev = world
    actor = (await db.execute(__import__("sqlalchemy").select(User).limit(1))).scalars().first()
    item = await items_service.create_item(
        db, ItemCreate(project_id=default.id, title="Open ticket"), actor
    )
    await mail_threading.record(
        db, message_id="<sent@radd>", item_id=item.id, direction=MailDirection.OUTBOUND
    )
    # A rule that WOULD have sent this to DEV, proving the chain was not consulted.
    db.add(_rule(source, MailRuleType.RECIPIENT.value, {"addresses": ["help@radd-hq.com"]}, project=dev))
    await db.flush()

    msg = EmailMessage()
    msg["Subject"] = "Re: Open ticket"; msg["From"] = "jane@customer.example"
    msg["To"] = "help@radd-hq.com"; msg["In-Reply-To"] = "<sent@radd>"
    msg["Message-ID"] = "<reply@x>"; msg.set_content("more info")
    outcome = await intake.accept(
        db,
        parsing.parse_email(msg.as_bytes()),
        raw=b"",
        default_project_key=default.key,
        own_addresses={"agent@radd-hq.com"},
        source_id=source.id,
    )
    assert outcome.result is intake.Result.APPENDED
    assert outcome.item_id == item.id  # stayed in Default, never re-routed
