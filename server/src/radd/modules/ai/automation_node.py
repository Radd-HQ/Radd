"""An AI classifier node for automation graphs (spec 116 phase 2).

The first node type contributed by a module OTHER than `automations`, which is
the point of it: it proves the `AutomationNodeSpec` seam carries a real feature
across a module boundary, not just a hello-world.

It is the storage router's trick (spec 102) applied to workflow: an admin writes
a prompt, enumerates the answers it may give, and each answer becomes an OUTPUT
PORT. "Is this a bug report, a feature request, or a question?" routes items down
three branches with no rules to maintain.

Why the answers must be enumerated rather than free text: `complete_choice`
constrains the model to exactly one of them, so a hallucinated fourth answer is
impossible by construction. A free-text classifier would need a fallback branch
for "the model said something else", which is a branch nobody would ever wire.

**Both arities (RADD-918).** "Is this batch urgent?" and "which of these are
bugs?" are different questions, and only the second one is usually what someone
means by an AI classifier:

* **Once for the whole set** — one question with a digest of every item
  appended, one answer, the whole packet down one port.
* **Once per item** — each item classified on its own and leaving by the port
  its OWN answer names. This is a partition, not a loop: the ports are the same,
  only the granularity of the answer moves.

Per item is the expensive mode and is bounded here rather than by the executor's
action budget, because the cost is model round trips: `ai_automation_max_classifications`
caps how many run, and everything past it takes the fallback port. `plan_items`
exists on the node spec for exactly this — the executor shares one session across
the walk and cannot parallelise a plugin's calls on its behalf, so the node that
knows its work is I/O-bound does it itself: contexts are built sequentially on
that session, then only the provider calls overlap.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Mapping

from radd.config import settings
from radd.kernel import AutomationNodeSpec

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
    """One port per answer, plus the fallback.

    This is why ports had to become a property of the node TYPE rather than of
    its kind: the set is a function of what someone typed into the form.
    """
    return (*answers_of(params), FALLBACK_PORT)


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
        "include": {
            "type": "object",
            "title": "What the model sees",
            "description": (
                "Which parts of each item are sent. Reads run as the automation's "
                "identity, so the prompt can only contain what it could already see."
            ),
            "properties": {
                "fields": {"type": "boolean", "default": True, "title": "Fields (type, state, priority, assignee, labels, custom fields)"},
                "description": {"type": "boolean", "default": True, "title": "Description (in full)"},
                "comments": {"type": "boolean", "default": False, "title": "Comments (all)"},
                "worklogs": {"type": "boolean", "default": False, "title": "Logged time"},
            },
        },
    },
}


async def plan(ctx: Any) -> str:
    """Classify the whole packet, and return the port it leaves by.

    Returns the fallback port rather than raising: one unreachable provider must
    not stop a graph that has other branches, and the run report records which
    port was taken either way.
    """
    answers = answers_of(ctx.node.params)
    if len(answers) < 2:
        return FALLBACK_PORT
    context = await _context_for(ctx, ctx.packet.item_ids)
    return await _ask(ctx, context, answers)


async def plan_items(ctx: Any) -> dict[uuid.UUID, str]:
    """Classify each item on its own — the partition mode.

    Two phases on purpose. The contexts are built FIRST, one after another,
    because they read through the walk's single `AsyncSession` and SQLAlchemy's
    async session is not safe for concurrent use. Only the provider calls, which
    touch no session at all, overlap.
    """
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
    """The REAL digest — fields, description and optionally comments/time. The
    first version sent only a count while saying it sent summaries, which made
    every answer noise."""
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
    kind="gate",  # routes the packet without changing the item set
    label="Ask the AI",
    description=(
        "Ask a question about the items and route them by the answer. Answers are "
        "enumerated, so the model cannot invent a branch that does not exist. Per "
        "item, each issue leaves by its own answer's port."
    ),
    group="Gates",
    params_schema=PARAMS_SCHEMA,
    ports_for=ports_for,
    needs_items=False,  # "nothing matched — is that a problem?" is a fair question
    # Default SET: it is the cheap mode, and defaulting to one model call per
    # item would make dropping this node on a scheduled run over a broad query
    # an expensive accident.
    arity="set",
    arity_options=("set", "item"),
    plan=plan,
    plan_items=plan_items,
)
