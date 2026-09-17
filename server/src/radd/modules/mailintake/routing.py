"""Where a new message opens its issue (RADD-958/961).

An ordered chain per source. First enabled rule that matches wins; nothing
matches → the source's default project. It is the `attachments/routing/` shape
deliberately: that module already proved the idea, including the two properties
that matter most here.

**Only the FIRST message in a thread is ever routed.** `intake.accept` resolves
threading before it reaches `_create`, so a reply lands on its existing issue and
never sees this file. No flag and no check — the pipeline order guarantees it.
That is worth knowing because the alternative, classifying every message, would
be both expensive and wrong: it would re-decide the project on message four.

**Every failure falls through.** A rule that raises, times out, or names a
project that no longer exists is skipped and the chain continues. A misrouted
ticket is an annoyance; a customer email dropped because a model was slow is not
survivable, and it is exactly what a naive implementation produces.

**Falling through is not the same as declining, and the chain now says which**
(RADD-989). Surviving every failure means a crashed rule and a rule that simply
did not match leave identical traces, so a rule broken for a release reads as a
rule that never applied — which is precisely what happened. Every rule the walk
consults leaves a `RuleOutcome`, and the dry run renders them.

**The trace is the whole chain, not the part that ran** (RADD-994). Consulting
only the enabled rules above the winner meant three different stories arrived as
the same silence: a rule switched off, a rule below the match, and a rule that
was deleted were all "not in the list". So the walk loads every rule and skips
the disabled ones in Python — one predicate's worth of work to make absence mean
exactly one thing — and a match records what it stopped. The cost is a handful of
in-memory rows on a path that was already reading them.

Rules are cheap-first by convention: address and subject matching costs nothing,
the AI classifier costs an inference, so the seeded order puts it last and only
mail that no deterministic rule claimed pays for it.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import MailRule
from .parsing import EmailPlan
from .types import NO_MATCH_ANSWER, MailRuleStatus, MailRuleType

logger = logging.getLogger(__name__)

#: An AI classification must not hold a mail transaction open indefinitely.
LLM_TIMEOUT_SECONDS = 15.0

#: Cap on a recorded failure string — it reaches an admin's screen, not a log file.
MAX_DETAIL_CHARS = 200

#: The destination line when the walk ended and nothing claimed the message. It
#: is the dataclass default and the one place this sentence is written: the dry
#: run used to restate it, which is how a chain whose rule actively DECLINED was
#: reported as a chain where nothing applied (RADD-994).
SOURCE_DEFAULT_REASON = "no rule matched — source default"

#: What a switched-off rule leaves behind (RADD-994). A disabled rule is not a
#: failure and not a decision; it is configuration, and saying so is the whole
#: point of giving it a row.
DISABLED_DETAIL = "switched off — the chain skipped it"


@dataclass(frozen=True)
class RuleOutcome:
    """What one rule did, kept whether it matched or not (RADD-989).

    The chain's per-rule `except` makes every failure survivable, which is right
    and which also means a crashed rule and a declining rule are indistinguishable
    downstream — the dry run reported both as "no rule matched". Recording the
    outcome turns that into an answer the preview can render.
    """

    rule_id: uuid.UUID | None
    rule_name: str
    status: MailRuleStatus
    detail: str = ""


@dataclass(frozen=True)
class RoutingDecision:
    """Where the message goes, and WHAT DECIDED — the second half is not
    decoration. "Why did this ticket open in the wrong project" is unanswerable
    without it, which is the complaint every routing chain eventually generates
    (storage learned this and surfaces `preempted_by`)."""

    project_id: uuid.UUID | None
    matched_rule_id: uuid.UUID | None = None
    matched_rule_name: str = ""
    #: Always accurate, never restated downstream (RADD-994) — a caller that
    #: recomputes this sentence from `project_id` alone reports a rule that
    #: declined, and a rule that matched but names no project, as nothing having
    #: happened at all.
    reason: str = SOURCE_DEFAULT_REASON
    #: Every rule in the chain, in order — consulted, skipped or never reached.
    outcomes: tuple[RuleOutcome, ...] = ()


def _addresses(plan: EmailPlan) -> set[str]:
    return {address.lower() for address in plan.recipients if address}


def _match_recipient(plan: EmailPlan, config: dict) -> bool:
    """Alias routing: `pipeline@radd-hq.com` → DEV.

    Matches the ADDRESS, never the raw header — `To: Pipeline Team
    <PIPELINE@radd-hq.com>` is the same alias, and a substring match on the
    header would also fire on a display name containing the word.

    On Migadu (and most hosts) an alias delivers into a shared mailbox, so the
    poller sees one connection and the alias exists only in the headers. That is
    why this reads `plan.recipients` — To/Cc/Delivered-To/X-Original-To — rather
    than anything about the connection.
    """
    wanted = {value.strip().lower() for value in config.get("addresses", []) if value.strip()}
    return bool(wanted & _addresses(plan))


def _match_sender(plan: EmailPlan, config: dict) -> bool:
    """A sender address, or a whole domain written as `@example.com`."""
    sender = (plan.sender_email or "").lower()
    if not sender:
        return False
    _, _, domain = sender.partition("@")
    for raw in config.get("patterns", []):
        value = raw.strip().lower()
        if not value:
            continue
        if value.startswith("@"):
            if domain == value[1:]:
                return True
        elif sender == value:
            return True
    return False


def _match_subject(plan: EmailPlan, config: dict) -> bool:
    """Case-insensitive substring. Deliberately not a regex: a rule that can hang
    the intake path on a pathological pattern is not worth the expressiveness,
    and anything subtler belongs in an automation on `mail.received`."""
    subject = (plan.subject or "").lower()
    return any(
        value.strip().lower() in subject
        for value in config.get("contains", [])
        if value.strip()
    )


class LlmVerdict(NamedTuple):
    """A classification's answer, and what KIND of answer it is.

    Routing nowhere has two meanings and the difference is the whole point: the
    model saying "none of these" is the feature working, the provider timing out
    is the feature broken. Both leave the message on the source default, so the
    status has to be carried out of here — it cannot be inferred from
    `project_id is None`.
    """

    project_id: uuid.UUID | None
    status: MailRuleStatus
    detail: str


async def _match_llm(session: AsyncSession, plan: EmailPlan, config: dict) -> LlmVerdict:
    """Classify the CONTENT into one of an enumerated set of projects (RADD-961).

    Mirrors `attachments/routing/rules.py::LlmRule`, including the part that
    matters more than the classification: **every classification failure returns
    no project and the chain continues.** The ai module is optional and
    disableable, the toggle can be off, the provider can time out, and the model
    can answer something not in the map. None of those may cost a customer their
    email.

    The model picks from a fixed list via `complete_choice`, so it can never
    invent a project key — and the list always ends with `NO_MATCH_ANSWER`, so
    "this is not any of those" is a verdict it can reach instead of a wrong
    category it is cornered into (RADD-989).

    **`feature_enabled` is called OUTSIDE the guarded region on purpose.** A
    misconfigured feature (one missing from `ai.features`' dispatch tables) is a
    wiring bug, not a classification failure, and swallowing it here would file it
    under "fell through (unexpected)" beside every provider hiccup — which is what
    hid RADD-989 for a release. Letting it propagate costs no safety: `decide`'s
    per-rule `except` still keeps the message, and it now records the rule as
    ERRORED so the dry run says CRASHED rather than "no rule matched".
    """
    mapping = {
        str(entry.get("answer", "")): entry.get("project_id")
        for entry in config.get("answers", [])
        if entry.get("answer")
    }
    if not mapping:
        # Not a decline: a rule with no categories can never match, so calling it
        # "no match" would advertise broken configuration as working.
        return LlmVerdict(
            None, MailRuleStatus.ERRORED, "no categories configured — this rule can never match"
        )
    try:  # the ai module is optional — absent means fall through
        from radd.modules.ai import client as ai_client
        from radd.modules.ai import features as ai_features
        from radd.modules.ai.types import AiDisabledError, AiFeature, AiRole, AiUpstreamError
    except ImportError:
        # The ai plugin being absent is a supported deployment, not a fault.
        return LlmVerdict(None, MailRuleStatus.DECLINED, "the AI module is not installed")
    if not await ai_features.feature_enabled(session, AiFeature.MAIL_ROUTING):
        return LlmVerdict(
            None,
            MailRuleStatus.DECLINED,
            "AI mail routing is off, or the chat role is unassigned",
        )
    prompt = config.get("prompt") or (
        "Classify this support email into one of the given categories."
    )
    # Subject + body, capped: a classifier does not need the whole thread and a
    # 10k-character prompt is a slow, expensive way to learn the same answer.
    excerpt = f"Subject: {plan.subject}\n\n{plan.body}"[: config.get("max_chars", 2000)]
    try:
        choice = await asyncio.wait_for(
            ai_client.complete_choice(
                session,
                AiRole.CHAT,
                prompt=f"{prompt}\n\n---\n{excerpt}",
                choices=[*mapping, NO_MATCH_ANSWER],
            ),
            timeout=float(config.get("timeout_seconds", LLM_TIMEOUT_SECONDS)),
        )
    except (TimeoutError, AiUpstreamError, AiDisabledError) as exc:
        logger.warning("mail llm rule: fell through (%s)", exc.__class__.__name__)
        return LlmVerdict(
            None, MailRuleStatus.ERRORED, f"the classifier failed ({exc.__class__.__name__})"
        )
    except Exception as exc:  # noqa: BLE001 — never let a classifier cost an email
        logger.warning("mail llm rule: fell through (unexpected)", exc_info=True)
        return LlmVerdict(
            None, MailRuleStatus.ERRORED, f"the classifier failed ({type(exc).__name__}: {exc})"
        )
    if choice == NO_MATCH_ANSWER:
        # The verdict this rule exists to be able to give: off-topic mail lands on
        # the source default because the model SAID so, not because something broke.
        return LlmVerdict(None, MailRuleStatus.DECLINED, f"the model answered {NO_MATCH_ANSWER!r}")
    target = mapping.get(choice)
    if target is None:
        # `complete_choice` constrains the answer, so this is a provider that
        # ignored the constraint — a fault, not a decision.
        return LlmVerdict(
            None,
            MailRuleStatus.ERRORED,
            f"the model answered {choice!r}, which is not a category",
        )
    project_id = uuid.UUID(target) if isinstance(target, str) else target
    return LlmVerdict(project_id, MailRuleStatus.MATCHED, f"the model answered {choice!r}")


def _match_reason(rule: MailRule) -> str:
    """The destination line for a deterministic match.

    A rule that matches while naming NO project stops the chain and still lands
    on the source default, so "rule: X" would describe a destination the rule did
    not choose and the old fallback ("no rule matched") would deny that anything
    matched at all. Both are wrong in the same direction — they send an admin off
    to debug the rule that already did its job (RADD-994).
    """
    if rule.project_id is None:
        return f"rule: {rule.name} matched but names no project — source default"
    return f"rule: {rule.name}"


async def decide(
    session: AsyncSession, plan: EmailPlan, *, source_id: uuid.UUID | None
) -> RoutingDecision:
    """Walk the source's chain. Returns the first match, or an empty decision."""
    if source_id is None:
        return RoutingDecision(None, reason="no source — instance default")
    rows = await session.execute(
        select(MailRule)
        .where(MailRule.source_id == source_id)
        .order_by(MailRule.position, MailRule.created_at)
    )
    chain = list(rows.scalars())
    outcomes: list[RuleOutcome] = []

    def record(rule: MailRule, status: MailRuleStatus, detail: str = "") -> None:
        outcomes.append(RuleOutcome(rule.id, rule.name, status, detail[:MAX_DETAIL_CHARS]))

    def stopped_at(index: int) -> tuple[RuleOutcome, ...]:
        """The rest of the chain, recorded rather than dropped (RADD-994).

        A rule below the winner is not a rule that declined, and leaving it out
        made it indistinguishable from one that was deleted. Its position is the
        explanation, so the trace has to show the position.

        **A disabled rule down here still reads DISABLED**, not NOT_REACHED. Both
        are true of it and only one is worth saying: being off is unconditional,
        so acting on it always helps, while "the chain stopped above you" sends an
        admin to reorder a rule that would still not have fired. It also leaves
        NOT_REACHED meaning exactly one thing — enabled, and below the match.
        """
        outcomes.extend(
            RuleOutcome(
                later.id,
                later.name,
                MailRuleStatus.NOT_REACHED if later.enabled else MailRuleStatus.DISABLED,
                "" if later.enabled else DISABLED_DETAIL,
            )
            for later in chain[index + 1 :]
        )
        return tuple(outcomes)

    #: The last deliberate decline, if any. Only the classifier can articulate one
    #: — a deterministic rule declining is just "no match" — and it is the reason
    #: the destination line borrows when nothing claims the message.
    declined = ""
    for index, rule in enumerate(chain):
        if not rule.enabled:
            record(rule, MailRuleStatus.DISABLED, DISABLED_DETAIL)
            continue
        config = rule.config or {}
        try:
            if rule.rule_type == MailRuleType.LLM.value:
                verdict = await _match_llm(session, plan, config)
                record(rule, verdict.status, verdict.detail)
                if verdict.project_id is None:
                    if verdict.status is MailRuleStatus.DECLINED:
                        declined = f"AI classifier: {rule.name} declined — {verdict.detail}"
                    continue
                return RoutingDecision(
                    verdict.project_id, rule.id, rule.name,
                    f"AI classifier: {rule.name} — {verdict.detail}", stopped_at(index),
                )
            matched = {
                MailRuleType.RECIPIENT.value: _match_recipient,
                MailRuleType.SENDER.value: _match_sender,
                MailRuleType.SUBJECT.value: _match_subject,
            }.get(rule.rule_type)
            if matched is None:
                # A rule type with no handler is a broken rule, not a fussy one —
                # it can never match, so DECLINED would advertise it as working.
                logger.warning("mail routing: no handler for rule type %r", rule.rule_type)
                record(rule, MailRuleStatus.ERRORED, f"unknown rule type {rule.rule_type!r}")
                continue
            if matched(plan, config):
                record(rule, MailRuleStatus.MATCHED)
                return RoutingDecision(
                    rule.project_id, rule.id, rule.name, _match_reason(rule), stopped_at(index)
                )
            # No detail: DECLINED already means "ran, did not claim it", and the
            # panel renders a label saying exactly that. A detail repeating the
            # status is a second line that adds nothing and crowds out the rows
            # whose detail is the whole point (RADD-994).
            record(rule, MailRuleStatus.DECLINED)
        except Exception as exc:  # noqa: BLE001 — one broken rule must not cost the message
            logger.warning("mail routing: rule %r raised, skipped", rule.name, exc_info=True)
            record(rule, MailRuleStatus.ERRORED, f"{type(exc).__name__}: {exc}")
    # A decline is the model SAYING no, which is the feature working; reporting it
    # as "no rule matched" describes the one outcome the chain was given a vocabulary
    # for as the absence of any outcome at all (RADD-994).
    return RoutingDecision(
        None, reason=declined or SOURCE_DEFAULT_REASON, outcomes=tuple(outcomes)
    )
