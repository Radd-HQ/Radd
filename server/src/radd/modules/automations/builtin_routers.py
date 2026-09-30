"""The built-in gates, the SLQ filter, the search source and the trigger node as
`AutomationNodeSpec`s (RADD-1322): each gate's `plan` answers with a port."""

from __future__ import annotations

import uuid
from typing import Any, Callable, Mapping

from radd.kernel.specs import AutomationNodeSpec

from . import gates
from .conditions import EventFacts
from .types import (
    TYPE_FILTER_SLQ,
    TYPE_GATE_ENTERED_STATE_CATEGORY,
    TYPE_TRIGGER_EVENT,
    AutomationNodeKind,
    TYPE_GATE_CHANGED_BY,
    TYPE_GATE_PERSON_IN_TEAM,
    GatePerson,
    TYPE_GATE_FIELD_CHANGED,
    TYPE_GATE_PAYLOAD,
    TYPE_GATE_PROJECT,
    TYPE_GATE_STATE_CATEGORY,
    TYPE_SEARCH_SLQ,
    NodeArity,
    NodePort,
    SearchMode,
)

_TRUE_FALSE = (NodePort.TRUE.value, NodePort.FALSE.value)


async def _state_categories(ctx: Any) -> dict[uuid.UUID, str]:
    from sqlalchemy import select
    from radd.modules.items.models import WorkItem
    from radd.modules.workflow.models import State

    rows = await ctx.session.execute(select(WorkItem.id, State.category)
        .join(State, State.id == WorkItem.state_id).where(WorkItem.id.in_(ctx.packet.item_ids)))
    wanted = set(ctx.node.params.get("categories") or [])
    return {item_id: "true" if category in wanted else "false" for item_id, category in rows}


async def _all_state_categories(ctx: Any) -> str:
    answers = await _state_categories(ctx)
    return NodePort.TRUE if ctx.packet.item_ids and all(answers.get(i) == NodePort.TRUE for i in ctx.packet.item_ids) else NodePort.FALSE


async def gate_person_user_id(ctx: Any, who: str) -> uuid.UUID | None:
    """The user a membership gate's `person` param names (RADD-1498): the actor
    off the event, a role off the TARGET item (None when the packet speaks for
    several — at item arity the executor hands one at a time), else an email.
    Shared with contributed membership gates by duck typing on `ctx`."""
    person = str(who or "").strip().lower()
    if person == GatePerson.ACTOR:
        raw = ctx.packet.facts.actor_id
        try:
            return uuid.UUID(str(raw)) if raw else None
        except ValueError:
            return None
    resolved = await ctx.person(person)
    return resolved.user_id if resolved is not None else None


async def _person_in_team(ctx: Any) -> str:
    from sqlalchemy import select
    from radd.modules.teams import service as teams_service
    from radd.modules.teams.models import Team

    params = ctx.node.params
    names = {str(v).strip() for v in (params.get("teams") or []) if str(v).strip()}
    user_id = await gate_person_user_id(ctx, params.get("person"))
    hit = False
    if names and user_id is not None:
        wanted = set((await ctx.session.execute(select(Team.id).where(Team.name.in_(names)))).scalars())
        hit = bool(wanted & await teams_service.user_team_ids(ctx.session, user_id))
    passed = not hit if params.get("negate") else hit
    return (NodePort.TRUE if passed else NodePort.FALSE).value


async def _entered_category(ctx: Any) -> str:
    from radd.modules.items import service as items
    from radd.modules.workflow import service as workflow

    raw = (ctx.packet.facts.payload.get("item") or {}).get("id")
    if not raw:
        return "false"
    item = await items.require_item(ctx.session, uuid.UUID(str(raw)))
    passed = await workflow.entered_categories(ctx.session, item.project_id, ctx.packet.facts.payload,
                                              set(ctx.node.params.get("categories") or []))
    return "true" if passed else "false"


def _gate(
    key: str,
    label: str,
    evaluator: Callable[[EventFacts, Mapping[str, Any]], bool],
    *,
    keywords: str,
    default_params: dict[str, Any],
    reads_event: bool,
) -> AutomationNodeSpec:
    async def plan(ctx: Any) -> str:
        passed = evaluator(ctx.packet.facts, ctx.node.params)
        return (NodePort.TRUE if passed else NodePort.FALSE).value

    return AutomationNodeSpec(
        key=key,
        kind=AutomationNodeKind.GATE.value,
        label=label,
        group="Gates",
        keywords=keywords,
        default_params=default_params,
        # FALSE is the last port, so an unknown answer or a failure takes it —
        # never a guess that the condition held.
        ports=_TRUE_FALSE,
        arity=NodeArity.SET.value,
        # A gate reads the EVENT, not the items: it has something to say about
        # an empty packet.
        needs_items=False,
        reads_event=reads_event,
        plan=plan,
    )


GATE_NODES: tuple[AutomationNodeSpec, ...] = (
    AutomationNodeSpec(
        key=TYPE_GATE_ENTERED_STATE_CATEGORY, kind=AutomationNodeKind.GATE.value, label="Entered state category", group="Gates",
        description="The triggering change moved into a category from outside it. Moving between two Done states does not count as entering Done again.",
        default_params={"categories": ["done"]},
        params_schema={"type": "object", "required": ["categories"], "properties": {
            "categories": {"type": "array", "title": "Categories", "items": {"type": "string"}, "minItems": 1}}},
        ports=_TRUE_FALSE, arity=NodeArity.SET.value, needs_items=False, reads_event=True, plan=_entered_category,
    ),
    # RADD-1265: the one open-ended gate — a dotted path, an operator, a value.
    _gate(
        TYPE_GATE_PAYLOAD, "Event value is", gates.payload_value_is,
        keywords="payload path value equals contains regex matches project release status any custom condition",
        default_params={"path": "", "operator": "eq", "value": "", "negate": False},
        reads_event=True,
    ),
    # RADD-1267: the only way to narrow a non-item event by project.
    _gate(
        TYPE_GATE_PROJECT, "Project is", gates.project_is,
        keywords="project key in scope which project release cycle form",
        default_params={"projects": [], "negate": False},
        reads_event=True,
    ),
    _gate(
        TYPE_GATE_FIELD_CHANGED, "Field changed", gates.field_changed,
        keywords="field changed from to transition state priority assignee custom moved became",
        default_params={"field": "state", "from_mode": "any", "from_values": [], "to_mode": "any", "to_values": []},
        reads_event=True,
    ),
    _gate(
        TYPE_GATE_CHANGED_BY, "Changed by", gates.changed_by,
        keywords="who actor person user did it made the change author",
        default_params={"users": [], "negate": False},
        reads_event=True,
    ),
    # RADD-1498: membership. Reads the event for the actor, the item for a role;
    # per item it partitions, so "the reporter is on Lighting" routes each issue.
    AutomationNodeSpec(
        key=TYPE_GATE_PERSON_IN_TEAM, kind=AutomationNodeKind.GATE.value, label="Person is in team", group="Gates",
        description="The person — the issue's reporter or assignee, whoever made the change, or an email — is on one of these teams, directory groups included.",
        keywords="team member membership reporter assignee actor person belongs department group",
        default_params={"person": GatePerson.REPORTER.value, "teams": [], "negate": False},
        params_schema={"type": "object", "required": ["person", "teams"], "properties": {
            "person": {"type": "string", "title": "Person"},
            "teams": {"type": "array", "title": "Teams", "items": {"type": "string"}, "minItems": 1},
            "negate": {"type": "boolean", "title": "Invert"}}},
        ports=_TRUE_FALSE, arity=NodeArity.SET.value, arity_options=(NodeArity.SET.value, NodeArity.ITEM.value),
        needs_items=False, reads_event=True, plan=_person_in_team,
    ),
    # Not event-reading: a draft being validated has a state, and asking about
    # its category is a real question.
    AutomationNodeSpec(
        key=TYPE_GATE_STATE_CATEGORY, kind=AutomationNodeKind.GATE.value, label="State category is", group="Gates",
        keywords="category done canceled progress todo backlog triage finished closed",
        default_params={"categories": []},
        reads_event=False,
        ports=_TRUE_FALSE, arity=NodeArity.SET.value, needs_items=True,
        description="All input issues are in the selected categories. Takes exactly one branch; an empty input takes false.",
        plan=_all_state_categories,
    ),
)


# --- the SLQ filter: the original per-item partition -------------------------


async def _filter_items(ctx: Any) -> dict[uuid.UUID, str]:
    """matched / unmatched per item. An empty query matches everything — a
    half-built filter narrows nothing rather than dropping everything."""
    from .executor import _load
    from .planning import condition_matches

    text = str(ctx.node.params.get("slq") or "").strip()
    ids = ctx.packet.item_ids
    if not text:
        return {item_id: NodePort.MATCHED.value for item_id in ids}
    assigned: dict[uuid.UUID, str] = {}
    for item, project in await _load(ctx.session, ids):
        if project is None:
            assigned[item.id] = NodePort.UNMATCHED.value
            continue
        try:
            hit = await condition_matches(ctx.session, text, item, project)
        except Exception:
            import logging

            logging.getLogger(__name__).exception("automations: filter %s failed on item %s", ctx.node.id, item.id)
            hit = False
        assigned[item.id] = (NodePort.MATCHED if hit else NodePort.UNMATCHED).value
    return assigned


async def _check_slq(session, params: Mapping[str, Any]) -> None:
    """A query that does not compile is an automation that finds nothing at 3am;
    the form is where that is fixable. `SlqError` propagates as the 422 it was."""
    from .service import _validate_condition

    await _validate_condition(session, str(params.get("slq") or ""))


FILTER_NODE = AutomationNodeSpec(
    key=TYPE_FILTER_SLQ,
    kind=AutomationNodeKind.FILTER.value,
    label="Filter issues (SLQ)",
    group="Filters",
    keywords="slq query where narrow matched unmatched branch condition if",
    default_params={"slq": ""},
    ports=(NodePort.MATCHED.value, NodePort.UNMATCHED.value),
    arity=NodeArity.ITEM.value,
    plan_items=_filter_items,
    check_async=_check_slq,
)


# --- the search source: the only built-in that PRODUCES items ---------------


async def _search(ctx: Any) -> tuple[uuid.UUID, ...]:
    """Run the node's query and return what it found — plus what arrived, in ADD
    mode. A query that no longer compiles (a custom field was deleted) finds
    nothing rather than taking the automation down."""
    from . import search

    try:
        found = await search.find_items(
            ctx.session,
            str(ctx.node.params.get("slq") or ""),
            project_key=str(ctx.node.params.get("project") or ""),
            label=f"{ctx.automation_name} / {ctx.node.id}",
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "automations: %s: search node %s failed", ctx.automation_name, ctx.node.id
        )
        found = ()
    if str(ctx.node.params.get("mode") or SearchMode.REPLACE.value) == SearchMode.ADD.value:
        return (*ctx.packet.item_ids, *found)
    return tuple(found)


SEARCH_NODE = AutomationNodeSpec(
    key=TYPE_SEARCH_SLQ,
    kind="source",
    label="Find issues (SLQ)",
    group="Sources",
    keywords="search find query slq lookup fetch produce items source others related",
    # REPLACE by default: the common case reaches somewhere else entirely.
    default_params={"slq": "", "project": "", "mode": "replace"},
    ports=(NodePort.OUT.value,),
    arity=NodeArity.SET.value,
    needs_items=False,
    plan=_search,
    check_async=_check_slq,
)


#: The trigger node — registered so every stored node TYPE has a spec.
TRIGGER_NODE = AutomationNodeSpec(
    key=TYPE_TRIGGER_EVENT,
    kind=AutomationNodeKind.TRIGGER.value,
    label="Trigger",
    group="Triggers",
    ports=(NodePort.OUT.value,),
    arity=NodeArity.SET.value,
    needs_items=False,
)

ROUTER_NODES: tuple[AutomationNodeSpec, ...] = (
    TRIGGER_NODE, *GATE_NODES, FILTER_NODE, SEARCH_NODE,
)
