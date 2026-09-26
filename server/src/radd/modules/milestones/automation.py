"""A plugin-contributed ACTION node acting on the plugin's OWN entity (RADD-923)
— the north-star's second half: the auto-wired `milestone.*` events declare
`subjects=("milestone",)`, this node declares `subject="milestone"`, and the
executor hands it the ids plus the savepoint, budget and loop guard that keep a
third-party action from destabilising a run. No edits to `automations`, the
kernel or the SPA."""

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
    """Decide, and write nothing. `ctx.subject_ids` are milestone ids (`subject="milestone"`)."""
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
    """Runs inside the executor's savepoint and `events.automated()`, so the
    `milestone.updated` it emits cannot re-trigger this automation. It emits at
    all so the change reaches audit, history and other automations."""
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
