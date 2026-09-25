"""The "Comment is…" gate (RADD-1248), owned by `comments` since RADD-1322.

It lived in `automations/gates.py`, which meant the automation engine knew the
shape of a comment event's payload. The module that emits the event now
contributes the question about it, through the same `AutomationNodeSpec` path
any plugin's gate takes. Nothing here imports `automations`.
"""

from __future__ import annotations

from typing import Any

from radd.sdk import AutomationNodeSpec

GATE_KEY = "gate.comment"
THREAD_ANY, THREAD_ROOT, THREAD_REPLY = "any", "root", "reply"
VISIBILITY_ANY = "any"
TRUE, FALSE = "true", "false"


def comment_is(payload: dict[str, Any], params: dict[str, Any]) -> bool:
    """Is the comment a root or a reply, and public or internal?

    Reads the comment event's own data: `parent_comment_id` (null on a root)
    and `visibility`. On an event that is not about a comment it answers False —
    a gate that can only be asked of a comment.
    """
    if "visibility" not in payload and "parent_comment_id" not in payload:
        return False
    thread = str(params.get("thread") or THREAD_ANY)
    is_reply = bool(payload.get("parent_comment_id"))
    if thread == THREAD_REPLY and not is_reply:
        return False
    if thread == THREAD_ROOT and is_reply:
        return False
    visibility = str(params.get("visibility") or VISIBILITY_ANY)
    if visibility != VISIBILITY_ANY and str(payload.get("visibility")) != visibility:
        return False
    return True


async def _plan(ctx: Any) -> str:
    return TRUE if comment_is(dict(ctx.packet.facts.payload or {}), dict(ctx.node.params)) else FALSE


COMMENT_GATE = AutomationNodeSpec(
    key=GATE_KEY,
    kind="gate",
    label="Comment is",
    group="Gates",
    keywords="comment reply root thread internal public discussion annotation",
    default_params={"thread": "any", "visibility": "any"},
    params_schema={
        "type": "object",
        "properties": {
            "thread": {"type": "string", "enum": [THREAD_ANY, THREAD_ROOT, THREAD_REPLY]},
            "visibility": {"type": "string", "enum": [VISIBILITY_ANY, "public", "internal"]},
        },
    },
    ports=(TRUE, FALSE),
    needs_items=False,
    reads_event=True,
    plan=_plan,
)
