import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError
from radd.kernel import changes
from radd.modules.events import service as events
from radd.modules.fields import service as fields
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.auth.types import Permission
from radd.modules.fields.models import FieldDefinition
from radd.modules.fields.types import BuiltinItemField
from radd.modules.items import slq
from radd.kernel.specs import valid_output_name

from radd import schedule as schedule_math
from radd.clock import utcnow
from . import graph
from . import nodes as nodes_registry
from . import templating
from .models import Automation, AutomationScheduleState, TriggerBinding, ValidationBinding
from .executor import ACTION_TYPE_PREFIX
from .schemas import (
    ActionAdapter,
    RuleCreate,
    RuleRead,
    RuleUpdate,
    TriggerRead,
    known_trigger,
)
from .email_action import is_role
from .types import (
    ARITY_PARAM,
    EVENT_GATE_TYPES,
    MAX_VALIDATION_TARGETS,
    SYSTEM_ACTOR_ID,
    TYPE_VALIDATION_FAIL,
    ActionType,
    AutomationNodeKind,
    AutomationEntity,
    AutomationEvent,
    AutomationTrigger,
    NodeArity,
    ValidationMode,
    ValidationTargetKind,
)

#: How a custom field is named in a finding's `field` — the `cf.<key>` form the
#: card-layout attribute catalogue and the SPA column ids already use, so one
#: vocabulary answers "which control does this point at" everywhere.
CUSTOM_FIELD_PREFIX = "cf."


logger = logging.getLogger(__name__)


async def _scope_definitions(session: AsyncSession) -> dict[str, FieldDefinition]:
    """key -> definition over the whole field registry (oldest wins on dup keys) —
    the scope a rule's condition is validated against on write."""
    by_key: dict[str, FieldDefinition] = {}
    for definition in await fields.list_fields(session):
        by_key.setdefault(definition.key, definition)
    return by_key


async def _validate_condition(session: AsyncSession, condition_slq: str) -> None:
    """Parse + compile the condition against the field registry. Any problem raises
    SlqError, which the items module's handler renders as 422 {detail, position}."""
    text = condition_slq.strip()
    if not text:
        return
    await slq.compile_query(
        session,
        slq.parse(text),
        definitions_by_key=await _scope_definitions(session),
        current_user_id=SYSTEM_ACTOR_ID,
        project_id=None,
    )


async def _validate_graph(
    session: AsyncSession,
    nodes: list[dict],
    edges: list[dict],
    actor_id: uuid.UUID | None = None,
) -> list[graph.Node]:
    """Structure first, then the parts only a database can check.

    `graph.validate` answers "is this a legal DAG with one trigger and real
    ports"; it is pure, so it cannot know whether a filter's SLQ compiles. Both
    run on write — the engine re-validates the structure on read, but a bad SLQ
    caught here is a 422 on the form instead of a filter that silently matches
    nothing at 3am.
    """
    try:
        parsed_nodes, parsed_edges = graph.parse(nodes, edges)
        triggers = graph.validate(parsed_nodes, parsed_edges, nodes_registry.ports_of)
    except graph.GraphError as exc:
        raise ConflictError(AutomationEntity.RULE, reason=str(exc)) from exc

    for trigger in triggers:
        try:
            known_trigger(str(trigger.params.get("event") or AutomationTrigger.MANUAL))
        except ValueError as exc:
            raise ConflictError(AutomationEntity.RULE, reason=str(exc)) from exc
        _check_trigger(trigger, parsed_nodes, parsed_edges)

    # `act_as` is a privilege, checked where it is WRITTEN. Checking it at run
    # time instead would mean an automation that saves cleanly and then quietly
    # refuses at 3am, and the field is hidden in the UI for anyone without the
    # atom — a hidden field that the API still accepts is not a permission.
    acting_as = {
        str(node.params.get("act_as") or "").strip()
        for node in parsed_nodes
        if node.kind is AutomationNodeKind.ACTION and node.params.get("act_as")
    }
    if acting_as and actor_id is not None:
        author = await session.get(User, actor_id)
        if author is not None:
            # A plain 403 naming the atom, not a 409: this is a permission
            # failure, and the editor hides the field entirely for anyone
            # without it — reaching here means the API was called directly.
            await authz.require(session, author, Permission.AUTOMATION_ACT_AS)

    for node in parsed_nodes:
        _check_arity(node)
        # A CONTRIBUTED node of ANY kind is checked against its own schema and
        # its own atom (RADD-923, widened by spec 119). It used to be actions
        # only, which left every contributed GATE — `ai.classify` since spec 116,
        # `ai.validate` now — storable with its required params blank: a node
        # that saves cleanly, sits on the canvas looking configured, and takes
        # its fallback port forever. Same rule as `act_as`: a check that only
        # bites at 3am is not a check.
        spec = nodes_registry.spec_for(node)
        if spec is not None:
            _check_node_schema(node, spec)
            await _require_node_permission(session, spec, actor_id)
            continue
        if node.kind in (AutomationNodeKind.FILTER, AutomationNodeKind.SOURCE):
            # A source's query is compiled on write for the same reason a
            # filter's is: a query that does not compile is an automation that
            # finds nothing at 3am, and the form is where that is fixable.
            await _validate_condition(session, str(node.params.get("slq") or ""))
        elif node.kind is AutomationNodeKind.ACTION:
            if node.type == TYPE_VALIDATION_FAIL:
                # Not in the action union and never will be: it applies nothing,
                # so it has no target service and no params the union describes.
                _check_validation_fail(node)
                continue
            # Params are an untyped envelope on the wire; the action union is
            # what type-checks them, exactly as it did when they were a rule
            # column. A ValidationError here is a 422 on the form.
            ActionAdapter.validate_python(
                {"type": node.type.removeprefix(ACTION_TYPE_PREFIX), "params": node.params}
            )
            _check_recipient_arity(node)

    _check_names(parsed_nodes)
    _check_token_references(parsed_nodes)

    detached = {n.id for n in parsed_nodes} - graph.is_reachable(
        [t.id for t in triggers], parsed_nodes, parsed_edges
    )
    if detached:
        # Not fatal — someone mid-build has every right to a dangling node — but
        # it is the quietest way for an automation to do nothing, so it is said
        # out loud rather than discovered later.
        logger.info(
            "automations: nodes not reachable from any trigger and will never run: %s",
            ", ".join(sorted(detached)),
        )
    return triggers


def _check_names(nodes: list[graph.Node]) -> None:
    """A node's NAME is what downstream tokens address it by (spec 120), so it is
    strict on write and lenient on read.

    Three refusals, each because the alternative is silent:

    * **Shape.** `Triage Result` cannot appear in `{{…}}` — the token grammar
      does not admit a space and would render the braces verbatim into somebody's
      issue. Refusing here is the only place anyone is looking at the field.
    * **Uniqueness.** Two nodes called `triage` make `{{triage.priority}}` mean
      whichever ran later, which is a graph whose behaviour depends on an
      ordering nobody wrote down.
    * **Reserved roots.** A node called `item` would shadow `{{item.key}}` in
      every action of the graph — and the shadowing would be invisible, because
      the token would keep resolving, just to something else.
    """
    seen: dict[str, str] = {}
    reserved = templating.reserved_roots()
    for node in nodes:
        name = str(node.name or "").strip()
        if not name:
            continue
        if not valid_output_name(name):
            raise ConflictError(
                AutomationEntity.RULE,
                reason=(
                    f"node {node.id!r}: {name!r} is not a usable name — lowercase "
                    f"letters, digits and underscores, starting with a letter "
                    f"(up to 30 characters)"
                ),
            )
        if name in reserved:
            raise ConflictError(
                AutomationEntity.RULE,
                reason=(
                    f"node {node.id!r}: {name!r} is already a template word "
                    f"(one of {', '.join(sorted(reserved))}) — a node with that "
                    f"name would shadow it everywhere in this graph"
                ),
            )
        if name in seen:
            raise ConflictError(
                AutomationEntity.RULE,
                reason=(
                    f"node {node.id!r}: {name!r} is already the name of node "
                    f"{seen[name]!r} — a token could only mean one of them"
                ),
            )
        seen[name] = node.id


def _check_token_references(nodes: list[graph.Node]) -> None:
    """Every `{{name.field}}` in the graph names a node that exists and an output
    it declares (spec 120).

    Caught on WRITE because the alternative is the failure this whole spec is
    about: a token that resolves to nothing is an action that does not happen at
    3am, and the commonest way to get one is renaming the producer and leaving
    the consumer behind. The message names the token AND the node holding it, so
    the fix is a click rather than a search.

    Two deliberate limits. UPSTREAM-ness is not checked — a graph mid-build has
    every right to a producer that is not wired yet, and the editor's picker
    offers only reachable producers anyway; a token whose producer never ran is a
    recorded skip at run time. And a producer that declares NO outputs (a
    contributed node that never said what it makes) accepts any field: refusing
    there would punish the plugin's user for the plugin's silence.
    """
    reserved = templating.reserved_roots()
    declared: dict[str, set[str]] = {}
    for node in nodes:
        name = nodes_registry.output_name(node)
        if name:
            declared[name] = {field.name for field in nodes_registry.outputs_of(node)}

    for node in nodes:
        for literal, token in _tokens_in(node.params):
            root, dot, field_name = token.partition(".")
            if not dot or root in reserved:
                continue
            if root not in declared:
                # The message NAMES both vocabularies. A `{{reporter.name}}`
                # written in the canned-response style is the likeliest way to
                # meet this refusal, and "no node is named 'reporter'" alone
                # does not tell someone that `reporter` was never a template
                # word here — the built-in roots are the other half of the
                # answer, and there are only six of them.
                raise ConflictError(
                    AutomationEntity.RULE,
                    reason=(
                        f"node {node.id!r} uses {literal}, but no node in this "
                        f"automation is named {root!r}"
                        + (
                            f" — named nodes are {', '.join(sorted(declared))}"
                            if declared
                            else " (no node has been given a name yet)"
                        )
                        + f"; the built-in roots are {', '.join(sorted(reserved))}"
                    ),
                )
            outputs = declared[root]
            if outputs and field_name not in outputs:
                raise ConflictError(
                    AutomationEntity.RULE,
                    reason=(
                        f"node {node.id!r} uses {literal}, but {root!r} produces "
                        f"{', '.join(sorted(outputs))}"
                    ),
                )


def _tokens_in(value, seen: set[int] | None = None) -> list[tuple[str, str]]:
    """`("{{a.b}}", "a.b")` for every token anywhere in a params structure.

    Walked rather than read off a list of "the template params", because which
    params template is a per-action-type fact and a list of them here would be a
    second copy of the planner's own behaviour — one that goes stale the first
    time a param becomes tokenizable.
    """
    if isinstance(value, str):
        return [(match.group(0), match.group(1)) for match in templating.TOKEN_RE.finditer(value)]
    if isinstance(value, dict):
        return [token for entry in value.values() for token in _tokens_in(entry)]
    if isinstance(value, (list, tuple)):
        return [token for entry in value for token in _tokens_in(entry)]
    return []


def _check_node_schema(node: graph.Node, spec) -> None:
    """A contributed node's params against its own JSON Schema (RADD-923).

    Deliberately shallow — required keys, enum membership, and the two SCALAR
    BOUNDS the schema states at top level (`maxLength` on a string, `maxItems` on
    an array). A full JSON Schema validator here would be a second, stricter
    opinion than the SPA's generated form, and the two disagreeing is worse than
    either being loose: it produces a form that saves a value it just offered.
    Those two are safe because the generated form already respects them.

    Anything deeper is the NODE's own business, through `spec.check` — a
    constraint that lives inside an array's items cannot be read honestly from
    here, and leaving it unchecked is how a 20-field `ai.generate` stored fine,
    truncated to 8 at run time, and then refused the tokens for the other twelve
    with a message about outputs it "does not produce" (spec 120).
    """
    schema = spec.params_schema or {}
    properties = schema.get("properties") or {}
    for key in schema.get("required") or []:
        if not str(node.params.get(key) or "").strip():
            raise ConflictError(
                AutomationEntity.RULE,
                reason=f"node {node.id!r} ({spec.key}): {key!r} is required",
            )
    for key, rule in properties.items():
        value = node.params.get(key)
        allowed = rule.get("enum")
        if allowed and value is not None and value not in allowed:
            raise ConflictError(
                AutomationEntity.RULE,
                reason=(
                    f"node {node.id!r} ({spec.key}): {key!r} must be one of "
                    f"{', '.join(map(str, allowed))}"
                ),
            )
        limit = rule.get("maxLength")
        if limit and isinstance(value, str) and len(value) > int(limit):
            raise ConflictError(
                AutomationEntity.RULE,
                reason=(
                    f"node {node.id!r} ({spec.key}): {key!r} is {len(value)} characters, "
                    f"and at most {limit} are allowed"
                ),
            )
        cap = rule.get("maxItems")
        if cap and isinstance(value, list) and len(value) > int(cap):
            raise ConflictError(
                AutomationEntity.RULE,
                reason=(
                    f"node {node.id!r} ({spec.key}): {key!r} holds {len(value)} entries, "
                    f"and at most {cap} are allowed"
                ),
            )

    if spec.check is None:
        return
    try:
        spec.check(node.params)
    except ValueError as exc:
        # A plugin's own refusal, in its own words, as a 409 on the form — the
        # same shape every other write-time check here takes.
        raise ConflictError(
            AutomationEntity.RULE, reason=f"node {node.id!r} ({spec.key}): {exc}"
        ) from exc


async def _require_node_permission(session: AsyncSession, spec, actor_id) -> None:
    """A contributed node's declared atom, checked where the automation is WRITTEN.

    Same rule as `act_as`: an automation that saves cleanly and then refuses at
    3am is worse than one that refuses now, and the editor hides what the caller
    cannot use — so reaching here without the atom means the API was called
    directly."""
    if not spec.permission or actor_id is None:
        return
    author = await session.get(User, actor_id)
    if author is not None:
        await authz.require(session, author, spec.permission)


def _check_arity(node: graph.Node) -> None:
    """A stored `arity` must be one the node type actually offers.

    Pydantic ignores unknown params, so a typo would otherwise be accepted and
    silently fall back to the default — the automation would run in a mode
    nobody chose, and the editor would keep showing the mode they typed."""
    raw = node.params.get(ARITY_PARAM)
    if raw is None:
        return
    rule = nodes_registry.arity_rule(node.type)
    if str(raw) not in {option.value for option in rule.options}:
        raise ConflictError(
            AutomationEntity.RULE,
            reason=(
                f"node {node.id!r} ({node.type}) cannot run {str(raw)!r} — "
                f"it supports {', '.join(option.value for option in rule.options)}"
            ),
        )


def _check_recipient_arity(node: graph.Node) -> None:
    """A ROLE recipient names a property of one item, so the action must run per
    item to have one.

    Caught on write rather than at run time because the failure is invisible
    otherwise: `send_email` addressed to `reporter` at set arity resolves no
    recipient and skip-logs, which is exactly what "email each reporter" did on
    every scheduled run before RADD-918 — a configured, saved, enabled
    automation that had never once sent a message.
    """
    action = node.type.removeprefix(ACTION_TYPE_PREFIX)
    if action not in (ActionType.SEND_EMAIL.value, ActionType.NOTIFY_USER.value):
        return
    target = str(node.params.get("to") or node.params.get("user") or "")
    if is_role(target) and nodes_registry.arity_of(node) is not NodeArity.ITEM:
        raise ConflictError(
            AutomationEntity.RULE,
            reason=(
                f"node {node.id!r}: {target!r} is a property of one issue, so this "
                f"action must run once per item — it would resolve no recipient "
                f"otherwise. Name an address instead, or switch it to per item."
            ),
        )


def _check_validate_trigger(trigger: graph.Node) -> None:
    """Spec 119 invariants for a VALIDATE trigger — strict where the reader is
    lenient (`validation.parse_targets`), because this is the only place someone
    can be told what they got wrong while they are still looking at the form.

    A trigger with no targets is refused rather than stored: it governs nothing,
    so it would sit in the list looking configured and never once run — the same
    silent-nothing failure the send_email role check exists to prevent.
    """
    raw_targets = trigger.params.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ConflictError(
            AutomationEntity.RULE,
            reason=(
                f"trigger {trigger.id!r}: a validation trigger needs at least one "
                f"target — a form, an issue type or a project"
            ),
        )
    if len(raw_targets) > MAX_VALIDATION_TARGETS:
        raise ConflictError(
            AutomationEntity.RULE,
            reason=(
                f"trigger {trigger.id!r}: at most {MAX_VALIDATION_TARGETS} targets "
                f"({len(raw_targets)} given)"
            ),
        )
    for entry in raw_targets:
        if not isinstance(entry, dict):
            raise ConflictError(
                AutomationEntity.RULE,
                reason=f"trigger {trigger.id!r}: each target must be {{kind, id}}",
            )
        try:
            ValidationTargetKind(str(entry.get("kind")))
        except ValueError as exc:
            raise ConflictError(
                AutomationEntity.RULE,
                reason=(
                    f"trigger {trigger.id!r}: unknown target kind {entry.get('kind')!r} — "
                    f"one of {', '.join(k.value for k in ValidationTargetKind)}"
                ),
            ) from exc
        try:
            uuid.UUID(str(entry.get("id")))
        except (ValueError, TypeError) as exc:
            raise ConflictError(
                AutomationEntity.RULE,
                reason=f"trigger {trigger.id!r}: target {entry.get('kind')} has no valid id",
            ) from exc
    mode = str(trigger.params.get("mode") or ValidationMode.ADVISORY.value)
    if mode not in set(ValidationMode):
        raise ConflictError(
            AutomationEntity.RULE,
            reason=(
                f"trigger {trigger.id!r}: mode must be "
                f"{' or '.join(m.value for m in ValidationMode)}"
            ),
        )


def _check_validation_fail(node: graph.Node) -> None:
    """A `validation.fail` node's own params (spec 119).

    `field` is checked loosely and only against SHAPE — a builtin name or
    `cf.<key>` — never against the live registry. A graph written when a custom
    field existed must keep producing readable advice after someone deletes it;
    it simply stops highlighting a control. Same philosophy as a card layout's
    departed attribute.
    """
    if not str(node.params.get("message") or "").strip():
        raise ConflictError(
            AutomationEntity.RULE,
            reason=(
                f"node {node.id!r}: a validation check needs a message — it is what the "
                f"person submitting reads"
            ),
        )
    target = str(node.params.get("field") or "").strip()
    if target and not (
        target.startswith(CUSTOM_FIELD_PREFIX) or target in set(BuiltinItemField)
    ):
        raise ConflictError(
            AutomationEntity.RULE,
            reason=(
                f"node {node.id!r}: {target!r} is not a field — use a builtin name "
                f"({', '.join(sorted(f.value for f in BuiltinItemField))}) or "
                f"{CUSTOM_FIELD_PREFIX}<key>"
            ),
        )


def _check_validate_gates(
    trigger: graph.Node, nodes: list[graph.Node], edges: list[graph.Edge]
) -> None:
    """No EVENT gate downstream of a validate trigger (spec 119).

    There is no event: `validation.validate_facts` builds a synthetic packet
    with the system actor, no diff and no changed fields, so
    `gate.field_changed` and `gate.changed_by` each answer a constant — and the
    branch behind the port they never take is a check that looks configured and
    can never run. The same reasoning as the schedule rule above, which is where
    the precedent comes from.

    Scoped to what this trigger can REACH rather than to the whole graph,
    because a graph may hold a validate trigger and an event trigger side by
    side — and on the event trigger's branch those gates are exactly right.
    """
    reachable = graph.is_reachable([trigger.id], nodes, edges)
    for node in nodes:
        if node.id in reachable and node.type in EVENT_GATE_TYPES:
            raise ConflictError(
                AutomationEntity.RULE,
                reason=(
                    f"node {node.id!r} ({node.type}) asks about the event that triggered "
                    f"the run, and a validation run has no event — it is a draft being "
                    f"submitted. Use a filter on the draft's own fields instead."
                ),
            )


def _check_trigger(
    trigger: graph.Node, nodes: list[graph.Node], edges: list[graph.Edge] | None = None
) -> None:
    """Spec 69 invariants, per TRIGGER node. Raised as 409 per the form-error idiom."""
    event = str(trigger.params.get("event") or AutomationTrigger.MANUAL)
    schedule = trigger.params.get("schedule")
    scheduled = event == AutomationTrigger.SCHEDULE
    if event == AutomationTrigger.VALIDATE:
        _check_validate_trigger(trigger)
        _check_validate_gates(trigger, nodes, edges or [])
    if scheduled and not isinstance(schedule, dict):
        raise ConflictError(
            AutomationEntity.RULE,
            reason=f"trigger {trigger.id!r}: a schedule trigger needs a schedule",
        )
    if not scheduled and schedule is not None:
        raise ConflictError(
            AutomationEntity.RULE,
            reason=f"trigger {trigger.id!r}: only a schedule trigger takes a schedule",
        )
    if scheduled:
        # The SHAPE, not just "is it a dict" (RADD-909). When triggers moved into
        # node params for spec 116, `params` became an untyped envelope and the
        # `ScheduleConfig` model stopped being applied to them — so a schedule
        # missing its time, or naming a day that no month has, was stored happily
        # and then blew up in the scheduler as a 500. Same seam the backup
        # schedules validate through, so the two cannot disagree.
        try:
            schedule_math.validate_config(schedule)
        except ValueError as exc:
            raise ConflictError(
                AutomationEntity.RULE, reason=f"trigger {trigger.id!r}: {exc}"
            ) from exc
    if scheduled and any(n.kind is AutomationNodeKind.GATE for n in nodes):
        # A gate reads the EVENT, and a schedule has none. The check stays
        # graph-wide rather than per-branch because a gate anywhere downstream of
        # a schedule trigger can only ever evaluate against nothing.
        raise ConflictError(
            AutomationEntity.RULE,
            reason="a scheduled automation cannot gate on event conditions (there is no event)",
        )


async def _sync_triggers(
    session: AsyncSession, rule: Automation, triggers: list[graph.Node]
) -> None:
    """Rebuild the automation's trigger bindings and their scheduler state.

    The graph is the source of truth; these rows are the index the engine and the
    scheduler query. Rebuilt wholesale on every write rather than diffed — a
    graph is small, and a diff is where a stale binding survives a node rename
    and keeps firing an automation nobody can see the trigger for.

    Schedule state is preserved per node where it can be: a rule saved for an
    unrelated reason must not silently reset a daily trigger's next_run_at and
    skip a day.
    """
    existing_states = {
        (state.automation_id, state.node_id): state
        for state in (
            await session.execute(
                select(AutomationScheduleState).where(
                    AutomationScheduleState.automation_id == rule.id
                )
            )
        ).scalars()
    }
    # Read the OLD schedules before the bindings go, so "did this trigger's
    # schedule change" can be answered without a second copy of it on the state
    # row. Without this the only options are re-anchoring every save (which can
    # push a daily run past its window) or never re-anchoring (which ignores an
    # edit).
    previous_schedules = {
        binding.node_id: binding.schedule
        for binding in (
            await session.execute(
                select(TriggerBinding).where(TriggerBinding.automation_id == rule.id)
            )
        ).scalars()
    }
    await session.execute(
        delete(TriggerBinding).where(TriggerBinding.automation_id == rule.id)
    )

    keep: set[tuple[uuid.UUID, str]] = set()
    for trigger in triggers:
        event = str(trigger.params.get("event") or AutomationTrigger.MANUAL)
        schedule = trigger.params.get("schedule")
        schedule = schedule if isinstance(schedule, dict) else None
        session.add(
            TriggerBinding(
                automation_id=rule.id,
                node_id=trigger.id,
                event_type=event,
                schedule=schedule,
            )
        )
        if event != AutomationTrigger.SCHEDULE or not rule.enabled or schedule is None:
            continue
        key = (rule.id, trigger.id)
        keep.add(key)
        state = existing_states.get(key)
        next_run_at = schedule_math.next_run(schedule, utcnow(), settings.scheduler_tz)
        if state is None:
            session.add(
                AutomationScheduleState(
                    automation_id=rule.id, node_id=trigger.id, next_run_at=next_run_at
                )
            )
        elif previous_schedules.get(trigger.id) != schedule:
            # Only re-anchor when the SCHEDULE itself changed. Recomputing on
            # every save would let a rename push a daily run past its window.
            state.next_run_at = next_run_at

    for key, state in existing_states.items():
        if key not in keep:
            await session.delete(state)
    await session.flush()


async def _sync_validations(
    session: AsyncSession, rule: Automation, triggers: list[graph.Node]
) -> None:
    """Rebuild the automation's validation bindings (spec 119).

    Wholesale, exactly like `_sync_triggers` and for the same reason: a diff is
    where a stale row survives a target being removed and keeps a form governed
    by a check nobody can see on the canvas. There is no per-row state to
    preserve here (a validate trigger has no clock), so the rebuild is total.
    """
    from .validation import parse_mode, parse_targets

    await session.execute(
        delete(ValidationBinding).where(ValidationBinding.automation_id == rule.id)
    )
    for trigger in triggers:
        if str(trigger.params.get("event") or "") != AutomationTrigger.VALIDATE:
            continue
        mode = parse_mode(trigger.params)
        for target in parse_targets(trigger.params):
            session.add(
                ValidationBinding(
                    automation_id=rule.id,
                    node_id=trigger.id,
                    target_kind=target.kind.value,
                    target_id=target.id,
                    mode=mode.value,
                )
            )
    await session.flush()


def _dump(models) -> list[dict]:
    return [m.model_dump(mode="json") for m in models or []]


async def create_rule(
    session: AsyncSession, data: RuleCreate, actor_id: uuid.UUID | None = None
) -> Automation:
    nodes, edges = _dump(data.nodes), _dump(data.edges)
    triggers = await _validate_graph(session, nodes, edges, actor_id)
    rule = Automation(
        name=data.name,
        enabled=data.enabled,
        nodes=nodes,
        edges=edges,
        position=data.position,
        orientation=data.orientation,
        created_by_id=actor_id,
    )
    session.add(rule)
    await session.flush()
    await _sync_triggers(session, rule, triggers)
    await _sync_validations(session, rule, triggers)
    await _emit(session, AutomationEvent.CREATED, rule, actor_id)
    return rule


async def update_rule(
    session: AsyncSession, rule_id: uuid.UUID, data: RuleUpdate, actor_id: uuid.UUID | None = None
) -> Automation:
    rule = await get_rule(session, rule_id)
    before = changes.snapshot(rule, RULE_FIELDS)
    if data.name is not None:
        rule.name = data.name
    if data.enabled is not None:
        rule.enabled = data.enabled
    if data.position is not None:
        rule.position = data.position

    # The graph is replaced whole or not at all. A partial update — new nodes
    # against old edges — is a graph nobody validated, and the halfway state is
    # exactly where a dangling edge would survive.
    if data.orientation is not None:
        rule.orientation = data.orientation

    if "nodes" in data.model_fields_set or "edges" in data.model_fields_set:
        nodes = _dump(data.nodes) if data.nodes is not None else rule.nodes
        edges = _dump(data.edges) if data.edges is not None else rule.edges
        triggers = await _validate_graph(session, nodes, edges, actor_id)
        rule.nodes, rule.edges = nodes, edges
    else:
        parsed = graph.parse(rule.nodes, rule.edges)
        triggers = graph.validate(*parsed, nodes_registry.ports_of)

    await session.flush()
    await _sync_triggers(session, rule, triggers)
    await _sync_validations(session, rule, triggers)
    await _emit(
        session,
        AutomationEvent.UPDATED,
        rule,
        actor_id,
        changes.diff_object(rule, before, hidden=("nodes", "edges")),
    )
    return rule


async def get_rule(session: AsyncSession, rule_id: uuid.UUID) -> Automation:
    rule = await session.get(Automation, rule_id)
    if rule is None:
        raise NotFoundError(AutomationEntity.RULE, rule_id)
    return rule


async def list_rules(session: AsyncSession) -> list[Automation]:
    result = await session.execute(
        select(Automation).order_by(Automation.position, Automation.created_at)
    )
    return list(result.scalars())


async def delete_rule(
    session: AsyncSession, rule_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    rule = await get_rule(session, rule_id)
    await _emit(session, AutomationEvent.DELETED, rule, actor_id)
    await session.delete(rule)


async def rules_for_trigger(
    session: AsyncSession, trigger: str
) -> list[tuple[Automation, str]]:
    """Enabled automations with a trigger binding for this event, paired with the
    NODE ID that matched, in evaluation order (engine seam).

    The node id is returned rather than looked up again because a graph may hold
    several triggers and the run must start at the one that fired — starting at
    "the trigger" is no longer a well-formed idea."""
    result = await session.execute(
        select(Automation, TriggerBinding.node_id)
        .join(TriggerBinding, TriggerBinding.automation_id == Automation.id)
        .where(
            Automation.enabled.is_(True),
            TriggerBinding.event_type == trigger,
        )
        .order_by(Automation.position, Automation.created_at)
    )
    return [(automation, node_id) for automation, node_id in result.all()]


async def manual_trigger_node(session: AsyncSession, rule_id: uuid.UUID) -> str | None:
    """The id of this automation's MANUAL trigger node, or None if it has none.

    "Is this a manual rule?" used to be a column read. Since spec 116 an
    automation may hold several triggers, so the question is really "does it have
    a manual entry point, and which node is it" — the run must start THERE, or a
    graph that also fires on a schedule would run the Monday branch when someone
    pressed the button."""
    return await session.scalar(
        select(TriggerBinding.node_id).where(
            TriggerBinding.automation_id == rule_id,
            TriggerBinding.event_type == AutomationTrigger.MANUAL.value,
        )
    )


async def rule_reads(session: AsyncSession, rules: list[Automation]) -> list[RuleRead]:
    """RuleRead payloads with each trigger's scheduler stamps, batch-hydrated.

    Batched deliberately: the settings list renders every automation, and a
    per-rule query here is the N+1 that turns a 30-automation page into 60
    round trips."""
    ids = [rule.id for rule in rules]
    bindings: dict[uuid.UUID, list[TriggerBinding]] = {}
    states: dict[tuple[uuid.UUID, str], AutomationScheduleState] = {}
    if ids:
        for binding in (
            await session.execute(
                select(TriggerBinding).where(TriggerBinding.automation_id.in_(ids))
            )
        ).scalars():
            bindings.setdefault(binding.automation_id, []).append(binding)
        for state in (
            await session.execute(
                select(AutomationScheduleState).where(
                    AutomationScheduleState.automation_id.in_(ids)
                )
            )
        ).scalars():
            states[(state.automation_id, state.node_id)] = state

    reads: list[RuleRead] = []
    for rule in rules:
        triggers = []
        for binding in sorted(bindings.get(rule.id, []), key=lambda b: b.node_id):
            state = states.get((rule.id, binding.node_id))
            triggers.append(
                TriggerRead(
                    node_id=binding.node_id,
                    event_type=binding.event_type,
                    schedule=binding.schedule,
                    next_run_at=state.next_run_at if state else None,
                    last_run_at=state.last_run_at if state else None,
                )
            )
        reads.append(RuleRead.model_validate(rule).model_copy(update={"triggers": triggers}))
    return reads


def _trigger_events(rule: Automation) -> set[str]:
    """The event types this graph's trigger nodes name, read off the graph.

    Read from `nodes` rather than the binding rows because `_emit` runs inside
    the same transaction that rebuilt them, and the graph is the source of truth
    either way."""
    events_named: set[str] = set()
    for node in rule.nodes or []:
        if isinstance(node, dict) and node.get("kind") == AutomationNodeKind.TRIGGER.value:
            params = node.get("params") or {}
            events_named.add(str(params.get("event") or AutomationTrigger.MANUAL))
    return events_named


#: What a rule edit can touch. The graph (nodes + edges) records only that it
#: changed — its JSON is the rule's design, not a value an auditor compares.
RULE_FIELDS: tuple[str, ...] = ("name", "enabled", "position", "orientation", "nodes", "edges")


async def _emit(
    session: AsyncSession,
    event_type: AutomationEvent,
    rule: Automation,
    actor_id: uuid.UUID | None,
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=AutomationEntity.RULE,
        entity_id=rule.id,
        actor_id=actor_id,
        # `triggers` (plural) since spec 116: a graph may fire from several
        # entry points, so a single `trigger` key could only ever name one of
        # them and would quietly misdescribe the rest.
        payload={
            "name": rule.name,
            "triggers": sorted(_trigger_events(rule)),
            "enabled": rule.enabled,
        },
        changes=diff,
    )
