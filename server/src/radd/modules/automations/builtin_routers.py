"""The built-in GATES, the SLQ FILTER, the search SOURCE and the validation
check, registered as `AutomationNodeSpec`s (RADD-1322).

Each gate is a pure evaluator in `gates.py` wrapped in a spec whose `plan`
answers with a port — the same contract `ai.classify` has always had, so the
executor routes a built-in gate and a contributed one through one path. The
two gates that knew another module's payload (`gate.comment`,
`gate.page_space`) moved to `comments` and `pages`, which own those shapes.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Mapping

from radd.kernel.specs import AutomationNodeSpec

from . import gates
from .conditions import EventFacts
from .types import (
    TYPE_FILTER_SLQ,
    TYPE_GATE_CHANGED_BY,
    TYPE_GATE_FIELD_CHANGED,
    TYPE_GATE_PAYLOAD,
    TYPE_GATE_PROJECT,
    TYPE_GATE_STATE_CATEGORY,
    TYPE_SEARCH_SLQ,
    TYPE_VALIDATION_FAIL,
    NodeArity,
    NodePort,
    SearchMode,
)

_TRUE_FALSE = (NodePort.TRUE.value, NodePort.FALSE.value)


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
        kind="gate",
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
    # Not event-reading: a draft being validated has a state, and asking about
    # its category is a real question.
    _gate(
        TYPE_GATE_STATE_CATEGORY, "State category is", gates.state_category_is,
        keywords="category done canceled progress todo backlog triage finished closed",
        default_params={"categories": []},
        reads_event=False,
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
    kind="filter",
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


# --- the spec-119 check ------------------------------------------------------


async def _plan_finding(ctx: Any) -> None:
    """Reaching this node IS the check failing. It records a finding and writes
    nothing, so a dry run and a live run record identically — and it returns
    None, which the executor reads as "nothing to put in the plan report".

    On an empty packet it stays quiet — THE APPLICABILITY RULE: `trigger →
    filter → matched → check` must not report on a draft the filter excluded.
    On a walk that is not collecting (an event walk) it is a pass-through."""
    from .executor import UNSPOKEN_FINDING

    if ctx.findings is None or not ctx.packet.item_ids:
        return None
    message = str(ctx.node.params.get("message") or "").strip()
    ctx.add_finding(message or UNSPOKEN_FINDING, str(ctx.node.params.get("field") or ""))
    return None


def _check_finding(params: Mapping[str, Any]) -> None:
    from radd.modules.fields.types import BuiltinItemField

    from .service import CUSTOM_FIELD_PREFIX

    if not str(params.get("message") or "").strip():
        raise ValueError("a validation check needs a message — it is what the person submitting reads")
    target = str(params.get("field") or "").strip()
    if target and not (target.startswith(CUSTOM_FIELD_PREFIX) or target in set(BuiltinItemField)):
        raise ValueError(
            f"{target!r} is not a field — use a builtin name "
            f"({', '.join(sorted(f.value for f in BuiltinItemField))}) or {CUSTOM_FIELD_PREFIX}<key>"
        )


VALIDATION_FAIL_NODE = AutomationNodeSpec(
    key=TYPE_VALIDATION_FAIL,
    kind="action",
    label="Report a problem",
    group="Actions",
    keywords="validation fail finding reject refuse check problem intake quality require",
    default_params={"message": "", "field": ""},
    ports=(NodePort.OUT.value,),
    arity=NodeArity.SET.value,
    needs_items=False,
    plan=_plan_finding,
    check=_check_finding,
)

#: The trigger node itself. Registered so every stored node TYPE has a spec
#: (RADD-1322); what it fires on is its `event` param, which the trigger
#: catalogue describes — its ports are a trigger's single `out`.
TRIGGER_NODE = AutomationNodeSpec(
    key="trigger.event",
    kind="trigger",
    label="Trigger",
    group="Triggers",
    ports=(NodePort.OUT.value,),
    arity=NodeArity.SET.value,
    needs_items=False,
)

ROUTER_NODES: tuple[AutomationNodeSpec, ...] = (
    TRIGGER_NODE, *GATE_NODES, FILTER_NODE, SEARCH_NODE, VALIDATION_FAIL_NODE,
)
