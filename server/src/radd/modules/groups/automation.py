"""The "Person is in directory group" automation gate (RADD-1498) — groups' own
node, because the mirror and its nested membership are this module's to read.

`person` is a role on the target item (reporter/assignee), `actor` (whoever
caused the event), or an email; `groups` lists ids, distinguished names or
names — any of the three, since the inspector stores the option's id while a
hand-written graph (or a template) would say the name. Membership is the
upward closure: a member of a nested child group is in the parent.
"""

import uuid
from typing import Any

from sqlalchemy import or_, select

from radd.sdk import AutomationNodeKind, AutomationNodeSpec, NodeArity, NodePort

from . import service
from .models import Group

GATE_KEY = "gate.person_in_group"
TRUE, FALSE = NodePort.TRUE.value, NodePort.FALSE.value
#: The event's actor, as `automations.types.GatePerson.ACTOR` spells it.
ACTOR = "actor"


async def _user_id(ctx: Any, who: str) -> uuid.UUID | None:
    person = str(who or "").strip().lower()
    if person == ACTOR:
        raw = ctx.packet.facts.actor_id
        try:
            return uuid.UUID(str(raw)) if raw else None
        except ValueError:
            return None
    # The host's person resolver (a role on the target item, else an email) —
    # duck-typed, so this module imports nothing of automations.
    resolved = await ctx.person(person)
    return resolved.user_id if resolved is not None else None


def _wanted_group_ids(values: list[str]):
    ids = []
    for value in values:
        try:
            ids.append(uuid.UUID(value))
        except ValueError:
            pass
    return select(Group.id).where(
        or_(Group.dn.in_(values), Group.name.in_(values), Group.id.in_(ids))
    )


async def _plan(ctx: Any) -> str:
    params = dict(ctx.node.params)
    values = [str(v).strip() for v in (params.get("groups") or []) if str(v).strip()]
    user_id = await _user_id(ctx, params.get("person"))
    hit = False
    if values and user_id is not None:
        wanted = set((await ctx.session.execute(_wanted_group_ids(values))).scalars())
        hit = bool(wanted & await service.user_group_ids(ctx.session, user_id))
    passed = not hit if params.get("negate") else hit
    return TRUE if passed else FALSE


PERSON_IN_GROUP_GATE = AutomationNodeSpec(
    key=GATE_KEY,
    kind=AutomationNodeKind.GATE.value,
    label="Person is in directory group",
    group="Gates",
    description=(
        "The person — the issue's reporter or assignee, whoever made the change, or an "
        "email — is in one of these directory groups, nested membership included."
    ),
    keywords="group directory ad ldap membership reporter assignee actor person belongs",
    default_params={"person": "reporter", "groups": [], "negate": False},
    params_schema={
        "type": "object",
        "required": ["person", "groups"],
        "properties": {
            "person": {"type": "string", "title": "Person"},
            "groups": {
                "type": "array",
                "title": "Groups",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "negate": {"type": "boolean", "title": "Invert"},
        },
    },
    ports=(TRUE, FALSE),
    arity=NodeArity.SET.value,
    arity_options=(NodeArity.SET.value, NodeArity.ITEM.value),
    needs_items=False,
    reads_event=True,
    plan=_plan,
)
