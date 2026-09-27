"""`ai.classify`: route items by the model's answer (spec 116).

The admin enumerates the answers; each is an output PORT, and `complete_choice`
constrains the model to one of them, so it cannot invent a branch. SET arity asks
once about the whole packet; ITEM (RADD-918) classifies each item and partitions
by its own answer, capped by `ai_automation_max_classifications` (overflow takes
the fallback port). The walk shares one session, so `plan_items` builds contexts
sequentially and overlaps only the provider calls.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Mapping

from radd.config import settings
from radd.kernel import AutomationNodeKind, AutomationNodeSpec, NodeArity, OutputField, OutputKind

from .automation_context import include_schema

logger = logging.getLogger(__name__)

NODE_KEY = "ai.classify"

#: The answers are the ports. A cap because each is a real output on the canvas,
#: and a classifier with twenty branches is a decision tree wearing a disguise.
MAX_ANSWERS = 8

#: Where the packet goes when the model is unreachable or answers nothing usable.
#: An explicit port rather than a silent halt: an automation that quietly stops
#: because the AI provider is down is indistinguishable from one that decided
#: nothing matched.
FALLBACK_PORT = "unavailable"


def answers_of(params: Mapping[str, Any]) -> list[str]:
    """The configured answers, trimmed, de-duplicated, order preserved."""
    seen: list[str] = []
    for raw in params.get("answers") or []:
        answer = str(raw).strip()
        if answer and answer not in seen:
            seen.append(answer)
    return seen[:MAX_ANSWERS]


def ports_for(params: Mapping[str, Any]) -> tuple[str, ...]:
    """One port per answer, plus the fallback."""
    return (*answers_of(params), FALLBACK_PORT)


#: The chosen answer, addressable downstream (spec 120). The classifier already
#: routes by it; naming it as an OUTPUT is what lets an action WRITE it —
#: "…and put the answer in the Category field" used to need a branch per answer
#: with a hardcoded action on each.
ANSWER_OUTPUT = "answer"


def outputs_for(params: Mapping[str, Any]) -> tuple[OutputField, ...]:
    """One ENUM output whose choices are the configured answers, so the write path
    can refuse a comparison against a value this classifier never produces."""
    return (
        OutputField(
            name=ANSWER_OUTPUT,
            label="Answer",
            kind=OutputKind.ENUM.value,
            choices=tuple(answers_of(params)),
            description="The answer the model chose — one of the configured answers.",
        ),
    )


PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["prompt", "answers"],
    "properties": {
        "prompt": {
            "type": "string",
            "title": "Question",
            "description": (
                "Asked with a digest of the items appended — the sections chosen "
                "below. Write it as a question with a small closed set of answers. "
                "Per item it is asked once per issue and each leaves by its own "
                "answer; for the whole set it is asked once about all of them."
            ),
            "maxLength": 2000,
        },
        "answers": {
            "type": "array",
            "title": "Possible answers",
            "description": "Each becomes an output port. The model can only reply with one of these.",
            "items": {"type": "string", "maxLength": 60},
            "minItems": 2,
            "maxItems": MAX_ANSWERS,
        },
        "include": include_schema(
            "Which parts of each item are sent. Reads run as the automation's "
            "identity, so the prompt can only contain what it could already see."
        ),
    },
}


async def plan(ctx: Any) -> str:
    """Classify the packet; return its port (the fallback, never a raise)."""
    answers = answers_of(ctx.node.params)
    if len(answers) < 2:
        return FALLBACK_PORT
    context = await _context_for(ctx, ctx.packet.item_ids)
    chosen = await _ask(ctx, context, answers)
    if chosen != FALLBACK_PORT:
        # Only a REAL answer is published (spec 120). The fallback means nobody
        # decided anything, and publishing "unavailable" as the answer would let
        # a downstream `set_custom_field {{triage.answer}}` write the word
        # "unavailable" into someone's field as though the model had said it.
        _publish(ctx, chosen)
    return chosen


def _publish(ctx: Any, answer: str) -> None:
    """`set_output` via getattr: `ai` imports nothing from `automations`."""
    publish = getattr(ctx, "set_output", None)
    if callable(publish):
        publish(ANSWER_OUTPUT, answer)


async def plan_items(ctx: Any) -> dict[uuid.UUID, str]:
    """Per-item partition; contexts built sequentially on the walk's one session
    (an AsyncSession is not safe for concurrent use), provider calls overlap."""
    answers = answers_of(ctx.node.params)
    item_ids = tuple(ctx.packet.item_ids)
    if len(answers) < 2:
        return {item_id: FALLBACK_PORT for item_id in item_ids}

    cap = max(0, settings.ai_automation_max_classifications)
    considered, overflow = item_ids[:cap], item_ids[cap:]
    if overflow:
        # Routed to the fallback, not dropped: a run that classified 50 of 200
        # items and one that classified all 200 must not look the same
        # downstream, and an item that silently leaves by no port at all is a
        # branch that quietly stops.
        logger.info(
            "ai.classify: %d of %d items past the %d-classification cap — routing them to %s",
            len(overflow), len(item_ids), cap, FALLBACK_PORT,
        )

    contexts = [(item_id, await _context_for(ctx, (item_id,))) for item_id in considered]

    limit = asyncio.Semaphore(max(1, settings.ai_automation_classify_concurrency))

    async def classify(context: str) -> str:
        async with limit:
            return await _ask(ctx, context, answers)

    results = await asyncio.gather(
        *(classify(context) for _, context in contexts), return_exceptions=True
    )
    assigned = {item_id: FALLBACK_PORT for item_id in overflow}
    for (item_id, _), result in zip(contexts, results):
        assigned[item_id] = result if isinstance(result, str) else FALLBACK_PORT
    return assigned


async def _context_for(ctx: Any, item_ids: tuple[uuid.UUID, ...]) -> str:
    """The digest the node's checkboxes select."""
    from radd.modules.ai.automation_context import ContextOptions, build_context

    return await build_context(
        ctx.session, item_ids, ctx.actor, ContextOptions.from_params(dict(ctx.node.params))
    )


async def _ask(ctx: Any, context: str, answers: list[str]) -> str:
    from radd.modules.ai import client as ai_client
    from radd.modules.ai.types import AiRole

    try:
        choice = await ai_client.complete_choice(
            ctx.session,
            AiRole.CHAT,
            prompt=f"{ctx.node.params.get('prompt', '')}\n\n{context}",
            choices=answers,
        )
    except Exception:
        logger.exception("ai.classify: provider unavailable; routing to %s", FALLBACK_PORT)
        return FALLBACK_PORT
    return choice if choice in answers else FALLBACK_PORT


SPEC = AutomationNodeSpec(
    key=NODE_KEY,
    kind=AutomationNodeKind.GATE.value,  # routes the packet without changing the item set
    label="Ask the AI",
    description=(
        "Ask a question about the items and route them by the answer. Answers are "
        "enumerated, so the model cannot invent a branch that does not exist. Per "
        "item, each issue leaves by its own answer's port."
    ),
    group="Gates",
    params_schema=PARAMS_SCHEMA,
    ports_for=ports_for,
    # Published at SET arity only: per item there is one answer per issue and the
    # packet's bag has one slot per node, so the executor drops them rather than
    # letting one node name silently mean whichever item came last.
    outputs_for=outputs_for,
    shape_params=("answers",),
    needs_items=False,  # "nothing matched — is that a problem?" is a fair question
    # Default SET: it is the cheap mode, and defaulting to one model call per
    # item would make dropping this node on a scheduled run over a broad query
    # an expensive accident.
    arity=NodeArity.SET.value,
    arity_options=("set", "item"),
    plan=plan,
    plan_items=plan_items,
)
