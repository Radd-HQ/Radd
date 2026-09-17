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

**And it must actually classify** (RADD-989). Every test below the fold used to
pin only the FALL-THROUGH side — disabled, no answers, raising — so the feature
shipped with `AiFeature.MAIL_ROUTING` missing from both of `ai.features`'
dispatch tables, `feature_enabled` raised KeyError at its call site, the chain's
per-rule `except` logged "rule raised, skipped", and every llm rule declined
every message for a release with a green suite. A suite that only proves the
safe direction proves the feature is safely absent.
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
from radd.modules.mailintake.types import (
    NO_MATCH_ANSWER,
    MailRuleStatus,
    MailRuleType,
    MailSourceKind,
)
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope


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


@pytest.fixture
async def admin(db):
    """Someone who may run the dry run. Created here rather than picked out of the
    table, so the test cannot silently start asserting about a leftover account."""
    user = User(
        email=f"ma-{uuid.uuid4().hex[:6]}@example.com",
        name="Mail admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def chat_role(db):
    """A RESOLVABLE chat role.

    `feature_enabled` is toggle AND role, so a test that stubbed the gate itself
    would pass for a reason production never has. This assigns a real role row
    against an unreachable endpoint — the model call is stubbed separately, so
    nothing leaves the process.
    """
    from radd.modules.ai import registry as ai_registry
    from radd.modules.ai.schemas import AiProviderCreate, AiRoleAssign
    from radd.modules.ai.types import AiRole, AiWireShape

    provider = await ai_registry.create_provider(
        db,
        AiProviderCreate(
            name=f"stub-{uuid.uuid4().hex[:8]}",
            wire_shape=AiWireShape.OPENAI,
            base_url="http://stub.invalid/v1",
            api_key="key-1",
            default_model="stub-model",
        ),
    )
    await ai_registry.set_role(db, AiRole.CHAT, AiRoleAssign(provider_id=provider.id))
    return provider


def _stub_choice(monkeypatch, answer):
    """Replace the ONE model call with a canned answer (or an exception to raise),
    and hand back the list of calls so a test can assert the model was reached —
    "the classifier declined" and "the classifier was never asked" are the two
    outcomes this whole issue is about telling apart."""
    from radd.modules.ai import client as ai_client

    calls: list[dict] = []

    async def fake_complete_choice(session, role, *, prompt, choices, **kwargs):
        calls.append({"role": role, "prompt": prompt, "choices": list(choices)})
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(ai_client, "complete_choice", fake_complete_choice)
    return calls


async def _set_mail_routing(db, enabled: bool):
    await settings_service.set_value(
        db, SettingKey.AI_MAIL_ROUTING, SettingScope.INSTANCE, None, enabled
    )


def _llm_rule(source, dev, **overrides):
    config = {
        "prompt": "classify",
        "answers": [{"answer": "dev", "project_id": str(dev.id)}],
    }
    config.update(overrides)
    return _rule(source, MailRuleType.LLM.value, config)


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


async def test_a_disabled_rule_is_skipped_but_still_appears_in_the_trace(db, world):
    """Skipped, and SAID to be skipped (RADD-994).

    The walk used to filter `enabled` in SQL, so a switched-off rule left no row
    at all — indistinguishable from one that was deleted. "Why didn't my rule
    fire" is the commonest routing question there is and the trace answered it
    with silence, which is the one answer that cannot be acted on.
    """
    source, _, dev = world
    db.add(_rule(source, MailRuleType.RECIPIENT.value, {"addresses": ["pipeline@radd-hq.com"]},
                 project=dev, enabled=False))
    await db.flush()
    plan = parsing.parse_email(message(to="pipeline@radd-hq.com"))
    decision = await routing.decide(db, plan, source_id=source.id)
    # It would have matched had it been on — which is exactly why its absence
    # from the trace was confusing.
    assert decision.project_id is None
    assert [o.status for o in decision.outcomes] == [MailRuleStatus.DISABLED]


async def test_the_rules_below_the_winner_are_recorded_as_not_reached(db, world):
    """Position is the explanation, so the trace has to show the position.

    With disabled rules now in the list, a rule missing from it means one thing:
    it does not exist. That only holds if the rules the walk stopped short of are
    in it too — otherwise "below the match" and "deleted" swap one silence for
    another.

    The middle rule pins the decided part: a disabled rule below the winner reads
    OFF, not "not reached". Both are true of it; only one is worth telling an
    admin, because reordering a switched-off rule changes nothing.
    """
    source, default, dev = world
    db.add(_rule(source, MailRuleType.RECIPIENT.value, {"addresses": ["help@radd-hq.com"]},
                 project=dev, position=1))
    db.add(_rule(source, MailRuleType.SUBJECT.value, {"contains": ["anything"]},
                 project=default, position=2, enabled=False))
    db.add(_rule(source, MailRuleType.SENDER.value, {"patterns": ["@customer.example"]},
                 project=default, position=3))
    await db.flush()

    decision = await routing.decide(db, parsing.parse_email(message()), source_id=source.id)
    assert decision.project_id == dev.id
    assert [o.status for o in decision.outcomes] == [
        MailRuleStatus.MATCHED, MailRuleStatus.DISABLED, MailRuleStatus.NOT_REACHED
    ]
    # The third rule WOULD have matched this sender. Not reached is not "no match".
    assert decision.outcomes[-1].rule_name


async def test_a_rule_that_matches_but_names_no_project_says_so(db, world):
    """It stops the chain and lands on the source default anyway (RADD-994).

    Two wrong sentences were available here and the code used both: `decide`
    said "rule: X", naming a destination the rule never chose, and the dry run
    recomputed it from `project_id` into "no rule matched", denying that anything
    matched at all. Either one sends an admin to debug the rule that behaved.
    """
    source, default, _ = world
    db.add(_rule(source, MailRuleType.RECIPIENT.value, {"addresses": ["help@radd-hq.com"]}))
    await db.flush()

    decision = await routing.decide(db, parsing.parse_email(message()), source_id=source.id)
    assert decision.project_id is None
    assert decision.outcomes[0].status is MailRuleStatus.MATCHED
    assert "names no project" in decision.reason
    assert (await intake._target_project(db, parsing.parse_email(message()), "", source.id)).id == default.id


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


async def test_an_llm_rule_classifies_and_routes_when_the_feature_is_on(
    db, world, chat_role, monkeypatch
):
    """**The RADD-989 regression.** With the toggle on, the chat role assigned and
    the model answering a configured category, the rule must MATCH.

    Nothing here stubs the gate: `feature_enabled` runs for real over the settings
    cascade and the role registry, so removing either `AiFeature.MAIL_ROUTING`
    entry from `ai.features` puts the KeyError back and fails this test. Every
    other llm test in this file passes with the feature entirely broken — that is
    what let the bug ship.
    """
    source, _, dev = world
    await _set_mail_routing(db, True)
    calls = _stub_choice(monkeypatch, "dev")
    db.add(_llm_rule(source, dev))
    await db.flush()

    decision = await routing.decide(db, parsing.parse_email(message()), source_id=source.id)
    assert calls, "the classifier was never asked — the gate refused before the model"
    assert decision.project_id == dev.id
    assert decision.outcomes[-1].status is MailRuleStatus.MATCHED


async def test_the_model_is_always_offered_a_none_of_these_answer(
    db, world, chat_role, monkeypatch
):
    """Off-topic mail must be able to DECLINE (RADD-989).

    The answer set is enumerated, so without an escape hatch the model is cornered
    into a wrong category on every message that fits none of them — the source
    default would be reachable only by failure. The extra choice is appended at
    ask time, never stored, so it cannot be edited into meaning something else.
    """
    source, default, dev = world
    await _set_mail_routing(db, True)
    calls = _stub_choice(monkeypatch, NO_MATCH_ANSWER)
    db.add(_llm_rule(source, dev))
    await db.flush()

    plan = parsing.parse_email(message())
    decision = await routing.decide(db, plan, source_id=source.id)
    assert calls[0]["choices"] == ["dev", NO_MATCH_ANSWER]
    assert decision.project_id is None
    # A verdict, not a breakage — and intake resolves it to the source default.
    assert decision.outcomes[-1].status is MailRuleStatus.DECLINED
    assert NO_MATCH_ANSWER in decision.outcomes[-1].detail
    assert (await intake._target_project(db, plan, "", source.id)).id == default.id


async def test_the_feature_being_off_declines_rather_than_erroring(
    db, world, chat_role, monkeypatch
):
    """An admin switching the toggle off is configuration, not a fault: the rule
    must read as DECLINED so the dry run does not cry wolf. It must also cost no
    inference — the gate runs before the model, not after it."""
    source, _, dev = world
    await _set_mail_routing(db, False)
    calls = _stub_choice(monkeypatch, "dev")
    db.add(_llm_rule(source, dev))
    await db.flush()

    decision = await routing.decide(db, parsing.parse_email(message()), source_id=source.id)
    assert decision.project_id is None
    assert decision.outcomes[-1].status is MailRuleStatus.DECLINED
    assert not calls


async def test_the_llm_rule_falls_through_when_no_chat_role_is_assigned(db, world, monkeypatch):
    """The other half of the gate. The toggle can be on while the role is
    unassigned — a fresh instance's normal state — and that may not cost a
    customer their email either."""
    source, _, dev = world
    await _set_mail_routing(db, True)
    calls = _stub_choice(monkeypatch, "dev")
    db.add(_llm_rule(source, dev))
    await db.flush()

    decision = await routing.decide(db, parsing.parse_email(message()), source_id=source.id)
    assert decision.project_id is None and not calls
    assert decision.outcomes[-1].status is MailRuleStatus.DECLINED


async def test_a_decline_reaches_the_destination_line_not_just_the_trace(
    db, world, admin, chat_role, monkeypatch
):
    """RADD-994's wording fix. The model answering "None of these" is the feature
    working, and the headline called it "no rule matched" — the one phrasing that
    says the chain had nothing to say. The destination line borrows the decline
    the way it already borrows a match.
    """
    from radd.modules.mailintake.config_schemas import RoutingPreviewRequest
    from radd.modules.mailintake.rules_router import preview_routing

    source, default, dev = world
    await _set_mail_routing(db, True)
    _stub_choice(monkeypatch, NO_MATCH_ANSWER)
    db.add(_llm_rule(source, dev))
    await db.flush()

    result = await preview_routing(
        source.id, RoutingPreviewRequest(recipient="help@radd-hq.com"), db, admin
    )
    assert result.project_id == default.id
    assert "declined" in result.reason and NO_MATCH_ANSWER in result.reason
    assert routing.SOURCE_DEFAULT_REASON not in result.reason


async def test_an_llm_rule_with_no_answers_is_reported_as_broken(db, world):
    """It can never match, so DECLINED would advertise broken configuration as
    working. The message still routes on."""
    source, _, _ = world
    db.add(_rule(source, MailRuleType.LLM.value, {"prompt": "classify", "answers": []}))
    await db.flush()
    decision = await routing.decide(db, parsing.parse_email(message()), source_id=source.id)
    assert decision.project_id is None
    assert decision.outcomes[-1].status is MailRuleStatus.ERRORED


async def test_a_rule_that_raises_is_skipped_and_the_chain_continues(db, world):
    """One broken rule must not cost the message — and must not stop a later
    rule that would have matched. It is recorded as ERRORED: surviving a failure
    is not the same as pretending it did not happen."""
    source, _, dev = world
    db.add(_rule(source, "not-a-real-type", {}, position=1))
    db.add(_rule(source, MailRuleType.RECIPIENT.value, {"addresses": ["help@radd-hq.com"]},
                 project=dev, position=2))
    await db.flush()
    decision = await routing.decide(db, parsing.parse_email(message()), source_id=source.id)
    assert decision.project_id == dev.id
    assert [o.status for o in decision.outcomes] == [
        MailRuleStatus.ERRORED, MailRuleStatus.MATCHED
    ]


async def test_a_classifier_that_raises_reads_as_failed_in_the_dry_run(
    db, world, admin, chat_role, monkeypatch
):
    """The preview must say CRASHED, never "no rule matched" (RADD-989).

    Both outcomes leave the message on the source default, so a preview that
    reports only the destination describes a broken rule and an inapplicable one
    identically — and the admin's next move is to rewrite a rule that was already
    correct. That is exactly how the KeyError survived a release.
    """
    from radd.modules.mailintake.config_schemas import RoutingPreviewRequest
    from radd.modules.mailintake.rules_router import preview_routing

    source, default, dev = world
    await _set_mail_routing(db, True)
    _stub_choice(monkeypatch, RuntimeError("boom"))
    db.add(_llm_rule(source, dev))
    await db.flush()

    result = await preview_routing(
        source.id, RoutingPreviewRequest(recipient="help@radd-hq.com"), db, admin
    )
    # Still routed — a failure never costs the message…
    assert result.project_id == default.id
    # …and the trace says why, loudly enough to act on.
    assert [o.status for o in result.outcomes] == [MailRuleStatus.ERRORED.value]
    assert "boom" in result.outcomes[0].detail


async def test_the_dry_run_records_every_rule_it_consulted(db, world, admin):
    """The trace is the chain, in order, up to the match — a deterministic rule
    that declined is as much of an answer as the one that matched."""
    from radd.modules.mailintake.config_schemas import RoutingPreviewRequest
    from radd.modules.mailintake.rules_router import preview_routing

    source, _, dev = world
    db.add(_rule(source, MailRuleType.SUBJECT.value, {"contains": ["[URGENT]"]},
                 project=dev, position=1))
    db.add(_rule(source, MailRuleType.RECIPIENT.value, {"addresses": ["help@radd-hq.com"]},
                 project=dev, position=2))
    await db.flush()

    result = await preview_routing(
        source.id, RoutingPreviewRequest(recipient="help@radd-hq.com", subject="hello"), db, admin
    )
    assert [o.status for o in result.outcomes] == [
        MailRuleStatus.DECLINED.value, MailRuleStatus.MATCHED.value
    ]
    assert result.project_id == dev.id


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
