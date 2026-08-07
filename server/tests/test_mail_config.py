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
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.mailintake import intake, parsing, registry, resolve, seeding, senders
from radd.modules.mailintake.models import MailRule, MailSender, MailSource
from radd.modules.mailintake.types import (
    KIND_DEFAULTS,
    MailRuleType,
    MailSenderKind,
    MailSourceKind,
)
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
    from radd.modules.mailintake.rules_router import preview_routing
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

    await seeding.seed(db)

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

    await seeding.seed(db)

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


# --- kind presets: Gmail / Outlook (RADD-969) --------------------------------------


async def test_a_preset_kind_answers_the_connection_the_row_leaves_blank():
    """The spec-110 rule, copied: the ROW STORES BLANK where the preset answers.

    Baking `smtp.gmail.com` into the row at save time looks identical on day one
    and is wrong the day the preset changes — every existing row would keep the
    old value. So the row holds nothing and resolution happens on the way out.
    """
    row = MailSender(
        name="Gmail", kind=MailSenderKind.GOOGLE.value, host="", port=0,
        from_address="Radd Support <support@radd-hq.com>", starttls=False,
    )
    assert resolve.sender_host(row) == "smtp.gmail.com"
    assert resolve.sender_port(row) == 587
    # `starttls` has no "unset", and the form HIDES it for a preset kind — so the
    # preset decides rather than a stale false riding out of a hidden control.
    assert resolve.sender_starttls(row) is True
    # Gmail's login IS the mailbox, so the form does not ask for it twice.
    assert resolve.sender_username(row) == "support@radd-hq.com"


async def test_an_explicit_value_beats_the_preset():
    """A preset is a default, not a lock — a relay in front of Gmail stays
    expressible."""
    row = MailSender(
        name="Relay", kind=MailSenderKind.GOOGLE.value, host="smtp.corp.example",
        port=2525, username="svc", from_address="a@x.com",
    )
    assert resolve.sender_host(row) == "smtp.corp.example"
    assert resolve.sender_port(row) == 2525
    assert resolve.sender_username(row) == "svc"


async def test_an_unknown_kind_resolves_to_nothing_rather_than_raising():
    """A row written by a newer version must degrade past the poller, not stop
    it walking the mailboxes that do work."""
    row = MailSource(name="future", kind="pigeon", host="", username="")
    assert resolve.source_host(row) == ""
    assert resolve.source_pollable(row) is False


async def test_polled_sources_includes_a_preset_mailbox_with_no_host(db):
    """Gmail and Outlook are polled exactly like IMAP, so the completeness check
    reads RESOLVED values — otherwise a correctly configured Gmail source is
    skipped silently for the rest of its life."""
    gmail = MailSource(
        name="gmail", kind=MailSourceKind.GOOGLE.value, address="help@radd-hq.com",
        username="help@radd-hq.com", secret="app-password", host="", port=0,
    )
    # Nothing but the address: the username falls back to it, so this is complete.
    outlook = MailSource(
        name="outlook", kind=MailSourceKind.OUTLOOK.value, address="help@radd-hq.com",
        secret="app-password", host="", port=0,
    )
    db.add_all([gmail, outlook])
    await db.flush()

    found = {s.name: s for s in await registry.polled_sources(db)}
    assert {"gmail", "outlook"} <= set(found)
    assert resolve.source_host(found["gmail"]) == "imap.gmail.com"
    assert resolve.source_port(found["gmail"]) == 993
    assert resolve.source_host(found["outlook"]) == "outlook.office365.com"
    assert resolve.source_username(found["outlook"]) == "help@radd-hq.com"


async def test_a_hand_configured_row_without_a_host_is_refused(db):
    """Saved-and-silently-skipped is indistinguishable, from the form, from
    working. The silence is right for a row someone is still editing and wrong
    for the moment they press Save."""
    with pytest.raises(ConflictError):
        await registry.save_source(
            db, MailSource(name="no host", kind=MailSourceKind.IMAP.value, username="u")
        )
    with pytest.raises(ConflictError):
        await registry.save_sender(
            db, MailSender(name="no host", kind=MailSenderKind.SMTP.value, from_address="a@x.com")
        )


async def test_a_preset_row_saves_with_no_host_at_all(db):
    saved = await registry.save_source(
        db,
        MailSource(
            name="gmail-ok", kind=MailSourceKind.GOOGLE.value, address="help@radd-hq.com",
            host="", port=0, secret="app-password",
        ),
    )
    assert saved.host == "", "the preset answers it; the row must stay blank"
    sender = await registry.save_sender(
        db,
        MailSender(
            name="gmail-out", kind=MailSenderKind.GOOGLE.value,
            from_address="a@radd-hq.com", host="", port=0,
        ),
    )
    assert sender.host == ""
    # A webhook has no host to speak of and must stay savable.
    await registry.save_source(
        db, MailSource(name="hook-ok", kind=MailSourceKind.WEBHOOK.value, secret="s")
    )


async def test_the_kinds_endpoint_tells_the_form_what_each_preset_answers(db, world):
    """The add form asks the SERVER what a kind means (spec 110's GET /sso/kinds).
    A client-side copy of `smtp.gmail.com` would need a redeploy to change, which
    is the whole point of not hardcoding it."""
    from radd.modules.mailintake.config_router import list_kinds

    actor, _, _ = world
    kinds = await list_kinds(db, actor)

    source_kinds = {k.kind: k for k in kinds.sources}
    sender_kinds = {k.kind: k for k in kinds.senders}
    assert set(source_kinds) == {k.value for k in MailSourceKind}
    assert set(sender_kinds) == {k.value for k in MailSenderKind}

    google_source = source_kinds[MailSourceKind.GOOGLE.value]
    assert google_source.preset is True and google_source.host == "imap.gmail.com"
    assert google_source.help_url.startswith("https://support.google.com/")
    assert google_source.guidance, "an app-password precondition nobody states is an auth failure"

    outlook_sender = sender_kinds[MailSenderKind.OUTLOOK.value]
    assert outlook_sender.preset is True
    assert (outlook_sender.host, outlook_sender.port, outlook_sender.starttls) == (
        "smtp-mail.outlook.com", 587, True,
    )
    # The kinds an operator configures in full: `preset` false is what makes the
    # form SHOW host/port instead of hiding them.
    assert source_kinds[MailSourceKind.IMAP.value].preset is False
    assert sender_kinds[MailSenderKind.SMTP.value].preset is False
    assert source_kinds[MailSourceKind.WEBHOOK.value].preset is False


async def test_a_google_sender_dispatches_to_the_smtp_transport(db, world, monkeypatch):
    """Gmail is SMTP with the connection answered. ONE dispatch point, so the
    test button cannot answer "no implementation" for a kind the RADD-968
    transport is sending through happily — which is what two copies produced."""
    from radd import smtp
    from radd.modules.mailintake.config_router import test_sender
    from radd.modules.mailintake.config_schemas import MailTestRequest

    actor, _, _ = world
    row = MailSender(
        name="Gmail out", kind=MailSenderKind.GOOGLE.value, host="", port=0,
        from_address="Radd <agent@radd-hq.com>", secret="app-password", starttls=False,
    )
    db.add(row)
    await db.flush()

    assert isinstance(senders.sender_for(row), senders.SmtpSender)

    used: dict = {}

    def fake_send(
        to_address, subject, body, *, to_name="", headers=None, html_body=None, config=None
    ):
        used["config"] = config
        return "<sent@gmail>"

    monkeypatch.setattr(smtp, "send_message", fake_send)
    result = await test_sender(row.id, MailTestRequest(to_address="you@example.com"), db, actor)

    assert result.ok and result.message_id == "<sent@gmail>"
    config = used["config"]
    assert (config.host, config.port, config.starttls) == ("smtp.gmail.com", 587, True)
    assert config.username == "agent@radd-hq.com"


async def test_a_hostless_preset_row_is_what_the_transport_sends_through(db, world, monkeypatch):
    """The seam between the RADD-968 transport and RADD-969 resolution.

    `outbound_configured` and `default_sender` both used to read `row.host`, and
    a Gmail row stores none — so notification mail and requester replies would
    have reported "nothing to send from" on an instance whose settings page said
    it was configured, while the test button sent fine. Both now go through
    `resolve`, and the transport dispatches through `senders.sender_for`, which
    is the only reason a preset sender works for anything but the test.
    """
    from radd import smtp
    from radd.modules.items import service as items_service
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.mailintake import transport

    actor, project, _ = world
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Printer on fire"), actor
    )

    row = MailSender(
        name="Gmail out", kind=MailSenderKind.GOOGLE.value, host="", port=0,
        from_address="agent@radd-hq.com", reply_to="help@radd-hq.com",
        secret="app-password", is_default=True,
    )
    await registry.save_sender(db, row)  # accepted with no host at all

    assert await registry.default_sender(db) is not None
    assert await transport.outbound_configured(db) is True

    used: dict = {}

    def fake_send(
        to_address, subject, body, *, to_name="", headers=None, html_body=None, config=None
    ):
        used["config"] = config
        used["headers"] = headers
        return "<sent@gmail>"

    monkeypatch.setattr(smtp, "send_message", fake_send)
    sent = await transport.send_item_mail(
        db, item_id=item.id, to_address="jane@customer.example",
        subject="[MC-1] Hello", text="body",
    )

    assert sent == "<sent@gmail>"
    config = used["config"]
    assert (config.host, config.port, config.starttls) == ("smtp.gmail.com", 587, True)
    assert config.username == "agent@radd-hq.com"  # the login IS the mailbox
    assert used["headers"]["Reply-To"] == "help@radd-hq.com"


async def test_the_env_relay_resolves_as_the_custom_smtp_kind(monkeypatch):
    """`_EnvSender` carries `kind="smtp"` so `resolve` treats it as the
    hand-configured kind it is. Were it to answer a preset kind, the env's own
    host would be overridden by Gmail's — a seed-era instance would silently
    start dialling the wrong relay."""
    monkeypatch.setattr(settings, "smtp_host", "relay.internal")
    monkeypatch.setattr(settings, "smtp_port", 2525)
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_username", "")

    from radd.modules.mailintake import transport

    relay = transport._env_sender()
    assert relay is not None
    assert isinstance(senders.sender_for(relay), senders.SmtpSender)
    assert resolve.sender_host(relay) == "relay.internal"
    assert resolve.sender_port(relay) == 2525
    assert resolve.sender_starttls(relay) is False  # the row wins; no preset to override
    assert resolve.sender_username(relay) == ""  # not a preset kind, so no address fallback


async def test_every_kind_has_a_preset_entry():
    """A kind with no entry would raise inside the kinds endpoint the moment it
    was added — a failure at the form, not at the point of the mistake."""
    for kind in (*MailSourceKind, *MailSenderKind):
        assert kind in KIND_DEFAULTS, f"{kind} has no preset entry"
        assert KIND_DEFAULTS[kind].name
