"""The validation VERDICT nodes: "Block submission" and "Warn submitter"
(RADD-1329).

Before this, a check node both decided and spoke: `ai.validate` was drawn as a
gate but wrote the findings itself, and whether they refused the submission was
the trigger's graph-wide `mode`, applied after the walk. Nothing on the canvas
said what blocked. The badges and the capped port explaining it were patches.

Now a check only ROUTES (and publishes what it found), and these two terminal
nodes are the only thing that can produce a finding:

* **Block submission** — its findings refuse the submission.
* **Warn submitter** — its findings are shown, and the person can submit again
  to create anyway.

So the graph reads literally — `check → fail → Block submission` — and what
blocks is visible from the node alone. Both have no output port and no apply
half: they record identically on a dry run and a live one.

A verdict node either says a fixed `message` (optionally aimed at a `field`), or
RELAYS the findings a named check published (`relay: <node id>`). A relayed
finding keeps the check's own grading on a Block node — a model-graded "minor"
problem advises even there — and never blocks on a Warn node.
"""

from __future__ import annotations

from typing import Any, Mapping

from radd.kernel.specs import AutomationNodeSpec

from .types import TYPE_VERDICT_BLOCK, TYPE_VERDICT_WARN, NodeArity

#: The only token roots a verdict's own message may use: the draft's. Anything
#: else — a search node's output, another node's variables — was read with the
#: automation's identity, usually wider than the submitter's, and the message is
#: shown to whoever submitted (spec 119's leak rule, enforced on write).
DRAFT_ROOTS = frozenset({"item"})


def _plan_for(blocking: bool):
    async def plan(ctx: Any) -> None:
        # Not a validation walk (an event walk passing through), or a branch an
        # upstream filter excluded this draft from: nothing to say.
        if ctx.findings is None or not ctx.packet.item_ids:
            return None
        relay = str(ctx.node.params.get("relay") or "").strip()
        if relay:
            for found in ctx.published_by(relay):
                ctx.add_finding(
                    str(found.get("message") or ""),
                    str(found.get("field") or ""),
                    blocking=blocking and bool(found.get("blocking", True)),
                    source=relay,
                )
            return None
        message = await ctx.render(str(ctx.node.params.get("message") or ""))
        ctx.add_finding(message, str(ctx.node.params.get("field") or ""), blocking=blocking)
        return None

    return plan


def _check(params: Mapping[str, Any]) -> None:
    from radd.modules.fields.types import BuiltinItemField

    from .service import CUSTOM_FIELD_PREFIX
    from .templating import TOKEN_RE

    relay = str(params.get("relay") or "").strip()
    message = str(params.get("message") or "").strip()
    if not relay and not message:
        raise ValueError(
            "say something — a message the person submitting reads, or relay a check's findings"
        )
    if relay and message:
        raise ValueError("either relay a check's findings or write a message, not both")
    for token in TOKEN_RE.findall(message):
        root = token.split(".", 1)[0]
        if root not in DRAFT_ROOTS:
            raise ValueError(
                f"{{{{{token}}}}} is not about the draft — a message shown to the person submitting "
                f"may only use {{{{item.*}}}}, since anything else was read with the automation's access"
            )
    target = str(params.get("field") or "").strip()
    if target and not (target.startswith(CUSTOM_FIELD_PREFIX) or target in set(BuiltinItemField)):
        raise ValueError(
            f"{target!r} is not a field — use a builtin name "
            f"({', '.join(sorted(f.value for f in BuiltinItemField))}) or {CUSTOM_FIELD_PREFIX}<key>"
        )


def _spec(key: str, label: str, blocking: bool, description: str, keywords: str) -> AutomationNodeSpec:
    return AutomationNodeSpec(
        key=key,
        kind="action",
        label=label,
        description=description,
        group="Validation",
        keywords=keywords,
        default_params={"message": "", "field": ""},
        # TERMINAL: no outlet. Chaining after a verdict is what made the old
        # "Report a problem" node look like it did something it did not.
        terminal=True,
        arity=NodeArity.SET.value,
        needs_items=False,
        plan=_plan_for(blocking),
        check=_check,
    )


BLOCK_NODE = _spec(
    TYPE_VERDICT_BLOCK,
    "Block submission",
    True,
    "Refuse the submission, and tell the person why. Only a Block node can refuse one.",
    "validation block refuse reject required stop intake verdict",
)
WARN_NODE = _spec(
    TYPE_VERDICT_WARN,
    "Warn submitter",
    False,
    "Show the person a problem; they can submit again to create it anyway.",
    "validation warn advise advisory flag intake verdict create anyway",
)

VERDICT_NODES: tuple[AutomationNodeSpec, ...] = (BLOCK_NODE, WARN_NODE)
