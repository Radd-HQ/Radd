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

Rules are cheap-first by convention: address and subject matching costs nothing,
the AI classifier costs an inference, so the seeded order puts it last and only
mail that no deterministic rule claimed pays for it.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import MailRule
from .parsing import EmailPlan
from .types import MailRuleType

logger = logging.getLogger(__name__)

#: An AI classification must not hold a mail transaction open indefinitely.
LLM_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class RoutingDecision:
    """Where the message goes, and WHAT DECIDED — the second half is not
    decoration. "Why did this ticket open in the wrong project" is unanswerable
    without it, which is the complaint every routing chain eventually generates
    (storage learned this and surfaces `preempted_by`)."""

    project_id: uuid.UUID | None
    matched_rule_id: uuid.UUID | None = None
    matched_rule_name: str = ""
    reason: str = "no rule matched — source default"


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


async def _match_llm(session: AsyncSession, plan: EmailPlan, config: dict) -> uuid.UUID | None:
    """Classify the CONTENT into one of an enumerated set of projects (RADD-961).

    Mirrors `attachments/routing/rules.py::LlmRule`, including the part that
    matters more than the classification: **every failure returns None and the
    chain continues.** The ai module is optional and disableable, the toggle can
    be off, the provider can time out, and the model can answer something not in
    the map. None of those may cost a customer their email.

    The model picks from a fixed list via `complete_choice`, so it can never
    invent a project key.
    """
    mapping = {
        str(entry.get("answer", "")): entry.get("project_id")
        for entry in config.get("answers", [])
        if entry.get("answer")
    }
    if not mapping:
        return None
    try:  # the ai module is optional — absent means fall through
        from radd.modules.ai import client as ai_client
        from radd.modules.ai import features as ai_features
        from radd.modules.ai.types import AiDisabledError, AiFeature, AiRole, AiUpstreamError
    except ImportError:
        return None
    if not await ai_features.feature_enabled(session, AiFeature.MAIL_ROUTING):
        return None
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
                choices=list(mapping),
            ),
            timeout=float(config.get("timeout_seconds", LLM_TIMEOUT_SECONDS)),
        )
    except (TimeoutError, AiUpstreamError, AiDisabledError) as exc:
        logger.warning("mail llm rule: fell through (%s)", exc.__class__.__name__)
        return None
    except Exception:  # noqa: BLE001 — never let a classifier cost an email
        logger.warning("mail llm rule: fell through (unexpected)", exc_info=True)
        return None
    target = mapping.get(choice)
    return uuid.UUID(target) if isinstance(target, str) else target


async def decide(
    session: AsyncSession, plan: EmailPlan, *, source_id: uuid.UUID | None
) -> RoutingDecision:
    """Walk the source's chain. Returns the first match, or an empty decision."""
    if source_id is None:
        return RoutingDecision(None, reason="no source — instance default")
    rows = await session.execute(
        select(MailRule)
        .where(MailRule.source_id == source_id, MailRule.enabled.is_(True))
        .order_by(MailRule.position, MailRule.created_at)
    )
    for rule in rows.scalars():
        config = rule.config or {}
        try:
            if rule.rule_type == MailRuleType.LLM.value:
                project_id = await _match_llm(session, plan, config)
                if project_id is None:
                    continue
                return RoutingDecision(
                    project_id, rule.id, rule.name, f"AI classifier: {rule.name}"
                )
            matched = {
                MailRuleType.RECIPIENT.value: _match_recipient,
                MailRuleType.SENDER.value: _match_sender,
                MailRuleType.SUBJECT.value: _match_subject,
            }.get(rule.rule_type)
            if matched is None:
                logger.warning("mail routing: no handler for rule type %r", rule.rule_type)
                continue
            if matched(plan, config):
                return RoutingDecision(rule.project_id, rule.id, rule.name, f"rule: {rule.name}")
        except Exception:  # noqa: BLE001 — one broken rule must not cost the message
            logger.warning("mail routing: rule %r raised, skipped", rule.name, exc_info=True)
    return RoutingDecision(None)
