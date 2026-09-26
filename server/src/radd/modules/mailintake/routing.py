"""Where a new message opens its issue (RADD-958/961): an ordered chain per
source, first enabled match wins, else the source's default project.

Only the FIRST message in a thread is routed — `intake.accept` resolves
threading first, so a reply never re-decides its project.

Every failure falls through (a raising rule, a timeout, a deleted project): a
misrouted ticket is an annoyance, a dropped email is not. Every rule leaves a
`RuleOutcome` — matched, declined, errored, disabled or not reached — so the
dry run can tell a crashed rule from one that did not match (RADD-989/994).
Cheap rules first by convention; the AI classifier is seeded last.
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

#: The destination line when nothing claimed the message — written only here, so
#: no caller can restate it over a rule that DECLINED (RADD-994).
SOURCE_DEFAULT_REASON = "no rule matched — source default"

#: What a switched-off rule leaves behind (RADD-994): configuration, not a failure.
DISABLED_DETAIL = "switched off — the chain skipped it"


@dataclass(frozen=True)
class RuleOutcome:
    """What one rule did, kept whether it matched or not (RADD-989), so the dry
    run can tell a crashed rule from a declining one."""

    rule_id: uuid.UUID | None
    rule_name: str
    status: MailRuleStatus
    detail: str = ""


@dataclass(frozen=True)
class RoutingDecision:
    """Where the message goes, and WHAT DECIDED — without it "why did this open in
    the wrong project" is unanswerable."""

    project_id: uuid.UUID | None
    matched_rule_id: uuid.UUID | None = None
    matched_rule_name: str = ""
    #: Never restated downstream (RADD-994): recomputed from `project_id` alone it
    #: reports a decline, or a match naming no project, as nothing happening.
    reason: str = SOURCE_DEFAULT_REASON
    #: Every rule in the chain, in order — consulted, skipped or never reached.
    outcomes: tuple[RuleOutcome, ...] = ()


def _addresses(plan: EmailPlan) -> set[str]:
    return {address.lower() for address in plan.recipients if address}


def _match_recipient(plan: EmailPlan, config: dict) -> bool:
    """Alias routing on the ADDRESS, never the raw header (a display name must not
    match); reads `plan.recipients` because aliases share a mailbox on most hosts."""
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
    """A classification's answer and its KIND: "none of these" (DECLINED) and a
    provider timeout (ERRORED) both route nowhere, so the status cannot be
    inferred from `project_id is None`."""

    project_id: uuid.UUID | None
    status: MailRuleStatus
    detail: str


async def _match_llm(session: AsyncSession, plan: EmailPlan, config: dict) -> LlmVerdict:
    """Classify the CONTENT into one of the configured projects (RADD-961).

    Every classification failure returns no project and the chain continues —
    the ai plugin is optional and a provider can time out. The model picks from a
    fixed list (`complete_choice`) ending with `NO_MATCH_ANSWER`, so declining is
    a verdict (RADD-989). `feature_enabled` runs OUTSIDE the guarded region on
    purpose: a wiring bug must surface as ERRORED, not as "fell through".
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
    from radd.modules.ai import client as ai_client
    from radd.modules.ai import features as ai_features
    from radd.modules.ai.types import AiDisabledError, AiFeature, AiRole, AiUpstreamError

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
    """The destination line for a deterministic match — which may name NO project
    and still stop the chain on the source default (RADD-994)."""
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
        """The rest of the chain as NOT_REACHED (enabled) or DISABLED — an off rule
        reads DISABLED even below a match, since that is the actionable fact (RADD-994)."""
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

    # The classifier's last decline: the destination line when nothing claims it.
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
            # No detail: the DECLINED label already says it (RADD-994).
            record(rule, MailRuleStatus.DECLINED)
        except Exception as exc:  # noqa: BLE001 — one broken rule must not cost the message
            logger.warning("mail routing: rule %r raised, skipped", rule.name, exc_info=True)
            record(rule, MailRuleStatus.ERRORED, f"{type(exc).__name__}: {exc}")
    # A decline is a verdict, not an absence (RADD-994).
    return RoutingDecision(
        None, reason=declined or SOURCE_DEFAULT_REASON, outcomes=tuple(outcomes)
    )
