"""Mail configuration as rows, and the wiring that makes it reachable (RADD-958).

The routing engine shipped before this and was **dead code**: nothing created a
source, nothing passed `source_id`, so `routing.decide` returned "no source" and
exited on every message. Its tests passed because they constructed rows and
passed the id by hand — honest tests of the engine that proved nothing about
whether production could ever call it.

So the assertions here are deliberately about REACHABILITY, not about matching:
that env seeds a row, that a source's own default is used, that a polled source
carries its id into intake, and that seeding is once-only. The matching itself is
`test_mail_routing.py`'s job.
"""

import uuid
from email.message import EmailMessage

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.mailintake import intake, parsing, registry
from radd.modules.mailintake.models import MailRule, MailSender, MailSource
from radd.modules.mailintake.types import MailRuleType, MailSenderKind, MailSourceKind
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
    suffix = uuid.uuid4().hex[:6]
    actor = User(
        email=f"mc-{suffix}@example.com", name="Cfg", instance_role=InstanceRole.ADMIN.value
    )
    db.add(actor)
    await db.flush()
    default = await projects_service.create_project(
        db, ProjectCreate(key=f"MC{suffix[:4].upper()}", name="Mail default")
    )
    dev = await projects_service.create_project(
        db, ProjectCreate(key=f"MD{suffix[:4].upper()}", name="Mail dev")
    )
    return actor, default, dev


def message(to="help@radd-hq.com", sender="jane@customer.example", subject="Hello") -> bytes:
    m = EmailMessage()
    m["Subject"] = subject
    m["From"] = sender
    m["To"] = to
    m["Message-ID"] = f"<{uuid.uuid4().hex}@customer.example>"
    m.set_content("body")
    return m.as_bytes()


# --- the wiring that was missing --------------------------------------------------


async def test_a_polled_source_carries_its_id_into_intake_so_rules_apply(db, world):
    """The whole point of RADD-958's second half. Before it, `source_id` was
    never passed and every rule chain was unreachable — the engine existed and
    could not be called."""
    _, default, dev = world
    source = MailSource(
        name="Inbox", kind=MailSourceKind.IMAP.value, address="help@radd-hq.com",
        host="imap.example.com", username="help@radd-hq.com", secret="x",
        default_project_id=default.id,
    )
    db.add(source)
    await db.flush()
    db.add(MailRule(
        source_id=source.id, name="pipeline alias", rule_type=MailRuleType.RECIPIENT.value,
        config={"addresses": ["pipeline@radd-hq.com"]}, project_id=dev.id, position=1,
    ))
    await db.flush()

    outcome = await intake.accept(
        db,
        parsing.parse_email(message(to="pipeline@radd-hq.com")),
        raw=b"",
        default_project_key="",
        own_addresses={"agent@radd-hq.com"},
        source_id=source.id,
        default_project_id=source.default_project_id,
    )
    assert outcome.result is intake.Result.CREATED
    item = await _item(db, outcome.item_id)
    assert item.project_id == dev.id, "the alias rule should have won"


async def test_a_source_default_is_used_when_nothing_matches(db, world):
    """The instance-wide RADD_MAIL_PROJECT_KEY is now the LAST resort, not the
    only answer — each mailbox carries its own default."""
    _, default, _ = world
    source = MailSource(
        name="Inbox", kind=MailSourceKind.IMAP.value, host="h", username="u",
        default_project_id=default.id,
    )
    db.add(source)
    await db.flush()

    outcome = await intake.accept(
        db, parsing.parse_email(message()), raw=b"", default_project_key="",
        own_addresses=set(), source_id=source.id, default_project_id=source.default_project_id,
    )
    item = await _item(db, outcome.item_id)
    assert item.project_id == default.id


async def _item(db, item_id):
    from radd.modules.items.models import WorkItem

    return await db.get(WorkItem, item_id)


async def test_the_dry_run_parses_addresses_the_way_a_real_message_does(db, world):
    """Found by running it: the preview built its `recipients` by splitting the
    raw input on commas, so `Pipeline Team <PIPELINE@radd-hq.com>` produced the
    whole display-name string and matched no rule — while the SAME address in a
    real message matched fine.

    A dry run that disagrees with the live chain is worse than no dry run: it
    reports a working rule as broken and sends someone off to fix nothing.
    """
    from radd.modules.mailintake.config_router import preview_routing
    from radd.modules.mailintake.config_schemas import RoutingPreviewRequest

    actor, default, dev = world
    source = MailSource(
        name="Inbox", kind=MailSourceKind.IMAP.value, address="help@radd-hq.com",
        host="h", username="u", default_project_id=default.id,
    )
    db.add(source)
    await db.flush()
    db.add(MailRule(
        source_id=source.id, name="alias", rule_type=MailRuleType.RECIPIENT.value,
        config={"addresses": ["pipeline@radd-hq.com"]}, project_id=dev.id, position=1,
    ))
    await db.flush()

    for recipient in (
        "pipeline@radd-hq.com",
        "Pipeline Team <PIPELINE@radd-hq.com>",       # display name + case
        "help@radd-hq.com, pipeline@radd-hq.com",      # several recipients
    ):
        result = await preview_routing(
            source.id, RoutingPreviewRequest(recipient=recipient), db, actor
        )
        assert result.project_id == dev.id, f"{recipient!r} should hit the alias rule"

    plain = await preview_routing(
        source.id, RoutingPreviewRequest(recipient="help@radd-hq.com"), db, actor
    )
    assert plain.project_id == default.id and not plain.matched_rule_id


# --- registry resolution ----------------------------------------------------------


async def test_polled_sources_skips_the_incomplete_and_the_disabled(db):
    """Half-filled configuration is the normal state of a form someone is still
    working on, and it must not produce a connection error every 60 seconds."""
    complete = MailSource(name="ok", kind=MailSourceKind.IMAP.value, host="h", username="u")
    no_host = MailSource(name="incomplete", kind=MailSourceKind.IMAP.value, username="u")
    disabled = MailSource(
        name="paused", kind=MailSourceKind.IMAP.value, host="h", username="u", enabled=False
    )
    push = MailSource(name="hook", kind=MailSourceKind.WEBHOOK.value, secret="s")
    db.add_all([complete, no_host, disabled, push])
    await db.flush()

    names = {s.name for s in await registry.polled_sources(db)}
    assert "ok" in names
    assert {"incomplete", "paused", "hook"}.isdisjoint(names)


async def test_a_webhook_source_with_no_address_matches_nothing(db):
    """The permissive reading — blank means any recipient — would let any address
    reach any tenant's ingest."""
    db.add(MailSource(name="blank", kind=MailSourceKind.WEBHOOK.value, secret="s"))
    await db.flush()
    assert await registry.source_for_address(db, "anything@example.com") is None


async def test_a_webhook_source_matches_its_address_case_insensitively(db):
    db.add(MailSource(
        name="hook", kind=MailSourceKind.WEBHOOK.value, address="Help@Radd-HQ.com", secret="s"
    ))
    await db.flush()
    assert (await registry.source_for_address(db, "help@radd-hq.com")) is not None


async def test_ambiguous_senders_resolve_to_none_rather_than_a_guess(db):
    """Silently sending as the wrong identity is worse than not sending."""
    db.add_all([
        MailSender(name="a", kind=MailSenderKind.SMTP.value, host="h", from_address="a@x.com"),
        MailSender(name="b", kind=MailSenderKind.SMTP.value, host="h", from_address="b@x.com"),
    ])
    await db.flush()
    assert await registry.default_sender(db) is None

    marked = MailSender(
        name="c", kind=MailSenderKind.SMTP.value, host="h", from_address="c@x.com", is_default=True
    )
    db.add(marked)
    await db.flush()
    chosen = await registry.default_sender(db)
    assert chosen is not None and chosen.name == "c"


async def test_marking_a_default_clears_the_others(db):
    first = MailSender(
        name="first", kind=MailSenderKind.SMTP.value, host="h", from_address="a@x.com",
        is_default=True,
    )
    await registry.save_sender(db, first)
    second = MailSender(
        name="second", kind=MailSenderKind.SMTP.value, host="h", from_address="b@x.com",
        is_default=True,
    )
    await registry.save_sender(db, second)

    rows = {s.name: s.is_default for s in await registry.list_senders(db)}
    assert rows["second"] is True and rows["first"] is False


async def test_own_addresses_unions_every_row(db):
    """The self-loop guard's set. A sending identity missing from it means Radd's
    own mail is taken for a customer's."""
    db.add(MailSource(
        name="in", kind=MailSourceKind.IMAP.value, address="Help@radd-hq.com",
        username="help@radd-hq.com", host="h",
    ))
    db.add(MailSender(
        name="out", kind=MailSenderKind.SMTP.value, host="h",
        from_address="Radd <AGENT@radd-hq.com>",
    ))
    await db.flush()
    found = await registry.own_addresses(db)
    assert {"help@radd-hq.com", "agent@radd-hq.com"} <= found


# --- env seeding is once-only -----------------------------------------------------


async def test_seeding_does_nothing_once_a_row_exists(db, monkeypatch):
    """The spec-101 rule: env creates the FIRST row and is never consulted
    again. Two sources of truth for one setting is how a screen ends up
    disagreeing with the running system."""
    monkeypatch.setattr(settings, "mail_imap_host", "imap.example.com")
    monkeypatch.setattr(settings, "mail_imap_username", "seed@example.com")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")

    db.add(MailSource(name="already here", kind=MailSourceKind.IMAP.value, host="h", username="u"))
    await db.flush()

    await registry._seed(db)

    names = [s.name for s in await registry.list_sources(db)]
    assert names == ["already here"], "env must not add a second source"


async def test_seeding_creates_a_source_and_sender_on_an_empty_instance(db, monkeypatch):
    monkeypatch.setattr(settings, "mail_imap_host", "imap.example.com")
    monkeypatch.setattr(settings, "mail_imap_username", "seed@example.com")
    monkeypatch.setattr(settings, "mail_imap_password", "pw")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from_address", "Radd <agent@example.com>")
    monkeypatch.setattr(settings, "mail_project_key", "")

    # A clean slate inside this transaction.
    for row in await registry.list_sources(db):
        await db.delete(row)
    for row in await registry.list_senders(db):
        await db.delete(row)
    await db.flush()

    await registry._seed(db)

    sources = await registry.list_sources(db)
    senders = await registry.list_senders(db)
    assert len(sources) == 1 and sources[0].host == "imap.example.com"
    assert sources[0].secret == "pw", "the credential must carry over, not just the host"
    assert len(senders) == 1 and senders[0].is_default is True


async def test_the_capability_snapshot_tracks_rows_not_env(db):
    """The kernel capability check is SYNC and cannot query; it reads a snapshot
    the registry refreshes on every write."""
    for row in await registry.list_sources(db):
        await db.delete(row)
    for row in await registry.list_senders(db):
        await db.delete(row)
    await db.flush()
    await registry.refresh_snapshot(db)
    assert registry.capability_state()["enabled"] is False

    await registry.save_source(
        db, MailSource(name="in", kind=MailSourceKind.IMAP.value, host="h", username="u")
    )
    assert registry.capability_state()["enabled"] is True
