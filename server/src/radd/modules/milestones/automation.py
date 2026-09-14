"""A plugin-contributed ACTION node, acting on the plugin's OWN entity (RADD-923).

This is the north-star's second half. `spec.py` proves a plugin can declare an
entity and get a table, CRUD, RBAC atoms, events and nav for free. This proves
the other direction: that those events are first-class in the automation engine,
and that the plugin can contribute the ACTION that responds to them — with no
edits to `automations`, the kernel, or the SPA.

Until RADD-923 that was impossible in two separate ways:

* A contributed action node could be DECLARED and never ran. `executor._run_action`
  did `ActionType(node.type)`, which raises for anything outside the built-in
  enum, logged "unknown action type" and dropped the node. So a plugin could add
  a trigger and a gate but never an action.
* Even if it had run, `milestone.created` carried `{"id": …, "project_id": …}` —
  a stub with no way to reach the row's own fields, and nothing in the packet
  identified a milestone at all. `Packet` knew only about items.

Now: the auto-wired `milestone.*` events declare `subjects=("milestone",)`, the
kernel writes the ref, `apply_event` reads it back into the packet, and this node
declares `subject="milestone"` and is handed the ids. The plugin writes a `plan`
and an `apply`; the executor supplies the savepoint, the budget and the loop
guard, which is what keeps a third-party action from being able to destabilise a
run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from radd.sdk import AutomationNodeSpec

from .models import Milestone

NODE_KEY = "milestone.set_status"

#: The statuses the node offers. A closed set for the same reason the AI
#: classifier enumerates its answers: an action whose parameter is free text
#: fails at APPLY time on a typo, and the form is where that is fixable.
STATUSES = ("open", "at_risk", "hit", "missed")

PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["status"],
    "properties": {
        "status": {
            "type": "string",
            "title": "Set the milestone's status to",
            "enum": list(STATUSES),
        }
    },
}


@dataclass
class _Plan:
    """What the node WOULD do. Returned by `plan`, applied by `apply` — the split
    is what makes the dry run free and identical to the real thing."""

    milestone_id: Any
    status: str
    detail: str
    resolves: bool = True


async def plan(ctx: Any) -> _Plan | None:
    """Decide, and write nothing.

    `ctx.subject_ids` is milestone ids because the spec says `subject="milestone"`
    — the node never learns how an item-shaped packet is assembled.
    """
    status = str(ctx.node.params.get("status") or "")
    if status not in STATUSES:
        return _Plan(None, status, f"set_status: {status!r} is not a milestone status", False)
    if not ctx.subject_ids:
        return _Plan(None, status, "set_status: no milestone reached this node", False)

    milestone_id = ctx.subject_ids[0]
    row = await ctx.session.get(Milestone, milestone_id)
    if row is None:
        return _Plan(milestone_id, status, "set_status: the milestone has gone", False)
    if row.status == status:
        # Reported rather than applied: a no-op that claims to have acted makes a
        # run report say something happened when nothing did.
        return _Plan(milestone_id, status, f"set_status: already {status!r}", False)
    return _Plan(milestone_id, status, f"set_status {row.title!r} -> {status!r}")


async def apply(ctx: Any, plan: _Plan) -> None:
    """Perform it, and say so on the stream.

    Runs inside the executor's SAVEPOINT and inside `events.automated()`, so the
    `milestone.updated` this emits is marked automation-caused and the engine
    skips it — an automation triggered by `milestone.updated` that also SETS a
    status cannot spin. The plugin gets that for free by applying here rather
    than reaching around the executor.

    Emitting at all is a choice worth naming: mutating the row silently would
    work, and would leave the change invisible to the audit log, the history feed
    and every other automation. A plugin's actions should be as visible as the
    product's own.
    """
    from radd.modules.events import service as events

    row = await ctx.session.get(Milestone, plan.milestone_id)
    if row is None:
        return
    previous = row.status
    row.status = plan.status
    await ctx.session.flush()
    await events.emit(
        ctx.session,
        event_type="milestone.updated",
        entity_type="milestone",
        entity_id=row.id,
        actor_id=getattr(ctx.actor, "id", None),
        subjects={"milestone": row.id},
        changes=[{"field": "status", "from": previous, "to": plan.status}],
    )


SPEC = AutomationNodeSpec(
    key=NODE_KEY,
    kind="action",
    label="Set milestone status",
    description=(
        "Set the status of the milestone this event is about. Contributed by the "
        "milestones plugin — no edits to the automations module."
    ),
    group="Milestones",
    params_schema=PARAMS_SCHEMA,
    subject="milestone",
    # Per milestone: the packet names one, and a set-arity reading would have to
    # pick one of several arbitrarily.
    arity="item",
    needs_items=False,  # it needs a MILESTONE, not an item — see `subject`
    permission="milestone.update",
    plan=plan,
    apply=apply,
)
