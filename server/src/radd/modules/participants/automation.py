"""Add participant, as an automation action this plugin contributes (RADD-1387).

Owned here so disabling the plugin withdraws the node (a stored graph naming it
then fails as "unknown action type"). It imports nothing from `automations`: the
kernel spec is the contract and the person param resolves through `ctx.person`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from radd.kernel import AutomationNodeSpec

from . import service
from .schemas import ParticipantAdd

#: Stored in every graph that uses the action, from when it was built in —
#: never rename it.
NODE_KEY = "action.add_participant"


class AddParticipantParams(BaseModel):
    user: str = Field(min_length=1, max_length=320)  # email, or reporter/assignee


@dataclass
class ParticipantPlan:
    detail: str
    resolves: bool = False
    item_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None


async def plan_add(ctx: Any) -> ParticipantPlan:
    """Who would be added, to which issue — read-only."""
    params = AddParticipantParams.model_validate(ctx.node.params)
    item = await ctx.target_item()
    if item is None:
        return ParticipantPlan("add_participant: no issue to add them to")
    person = await ctx.person(params.user)
    if person is None:
        return ParticipantPlan(f"add_participant: no user resolves for {params.user!r} on the issue")
    return ParticipantPlan(
        f"add_participant {person.named_as}", resolves=True, item_id=item.id, user_id=person.user_id
    )


async def apply_add(ctx: Any, plan: ParticipantPlan) -> None:
    # As the automation's actor: the service's own permission check applies.
    await service.add_participant(
        ctx.session, plan.item_id, ParticipantAdd(user_id=plan.user_id), ctx.actor
    )


def check(params: dict[str, Any]) -> None:
    AddParticipantParams.model_validate(params)


ADD_PARTICIPANT_NODE = AutomationNodeSpec(
    key=NODE_KEY,
    kind="action",
    label="Add participant",
    description="Share the issue with a person — by email, or its reporter or assignee — who then follows it.",
    group="Actions",
    keywords="add_participant share follow do apply",
    params_schema={
        "type": "object",
        "properties": {
            "user": {"type": "string", "maxLength": 320, "description": "An email, or reporter / assignee."},
        },
    },
    default_params={"user": ""},
    ports=("out",),
    # Fixed per item: sharing is a property of one issue.
    arity="item",
    needs_items=False,
    plan=plan_add,
    apply=apply_add,
    check=check,
)
