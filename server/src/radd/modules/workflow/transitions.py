"""Transition rows + enforcement (spec 61).

CRUD validates against the project's states and field registry; `check_transition`
is the items-module enforcement seam (re-exported via workflow.service) and
`allowed_transitions` feeds the UI's graying/tooltips. Estimate/comment/field
lookups go through the owning modules' public seams via deferred imports —
timelogging/comments/fields load after workflow (mirrors cycles→items).
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.fields.types import FieldType
from radd.kernel import changes
from radd.modules.events import service as events
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from . import guards
from .guards import ItemSnapshot, TransitionError
from .models import State, WorkflowTransition
from .schemas import (
    AllowedTarget,
    AllowedTransitions,
    TransitionCreate,
    TransitionRule,
    TransitionUpdate,
)
from .types import (
    BUILTIN_OPS,
    DATE_BUILTINS,
    ApproverKind,
    BuiltinField,
    ConditionKind,
    ConditionOp,
    TransitionCheck,
    TransitionEntity,
    TransitionEvent,
    TransitionMode,
    ops_for_field_type,
)


async def list_transitions(
    session: AsyncSession, project_id: uuid.UUID
) -> list[WorkflowTransition]:
    result = await session.execute(
        select(WorkflowTransition)
        .where(WorkflowTransition.project_id == project_id)
        .order_by(WorkflowTransition.position, WorkflowTransition.created_at)
    )
    return list(result.scalars())


async def get_transition(
    session: AsyncSession, transition_id: uuid.UUID
) -> WorkflowTransition:
    transition = await session.get(WorkflowTransition, transition_id)
    if transition is None:
        raise NotFoundError(TransitionEntity.TRANSITION, transition_id)
    return transition


async def _project_state(
    session: AsyncSession, project_id: uuid.UUID, state_id: uuid.UUID
) -> State:
    state = await session.get(State, state_id)
    if state is None or state.project_id != project_id:
        raise ConflictError(
            TransitionEntity.TRANSITION,
            reason=f"state {state_id} does not belong to the project",
        )
    return state


async def _validate_edge(
    session: AsyncSession,
    project_id: uuid.UUID,
    from_state_id: uuid.UUID | None,
    to_state_id: uuid.UUID,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    if from_state_id == to_state_id:
        raise ConflictError(
            TransitionEntity.TRANSITION, reason="from and to state must differ"
        )
    if from_state_id is not None:
        await _project_state(session, project_id, from_state_id)
    await _project_state(session, project_id, to_state_id)
    # Spec 107 follow-up: multiple rows per (from, to) are LEGITIMATE — each
    # scoped by applies_when, resolved first-match — so the old dupe 409 is
    # gone (a fully-shadowed duplicate is harmless, just never reached).


def _rule_error(reason: str) -> ConflictError:
    return ConflictError(TransitionEntity.TRANSITION, reason=reason)


async def _validate_rules(
    session: AsyncSession,
    project: Project,
    rules: Sequence[TransitionRule],
    applies_when: Sequence[dict] = (),
) -> None:
    """Spec 107 write-validation, all 409: require_field conditions (and the
    applies_when scoping conditions — same shape, same validator) must name a
    real field with an operator its type allows and well-formed values (the
    custom field's registry type is SNAPSHOTTED into params server-side);
    require_approval entries must name real, active subjects (their display
    names are snapshotted server-side too — never trusted from the client)."""
    definitions = None
    needs_registry = any(
        rule.check is TransitionCheck.REQUIRE_FIELD
        and rule.params.get("kind") == ConditionKind.CUSTOM.value
        for rule in rules
    ) or any(
        condition.get("kind") == ConditionKind.CUSTOM.value for condition in applies_when
    )
    if needs_registry:
        from radd.modules.fields import service as fields  # deferred: fields loads after workflow

        definitions = {
            d.key: d for d in await fields.definitions_for_project(session, project)
        }
    for rule in rules:
        if rule.check is TransitionCheck.REQUIRE_FIELD:
            _validate_field_rule(rule.params, definitions)
        elif rule.check is TransitionCheck.REQUIRE_APPROVAL:
            await _validate_approval_rule(session, rule.params)
    for condition in applies_when:
        _validate_field_rule(condition, definitions)


def _validate_field_rule(params: dict, definitions: dict | None) -> None:
    key = str(params.get("key") or "")
    try:
        kind = ConditionKind(params.get("kind"))
        op = ConditionOp(params.get("op"))
    except ValueError:
        raise _rule_error("a field condition needs a valid kind and operator") from None
    if not key:
        raise _rule_error("a field condition needs a field")
    if kind is ConditionKind.BUILTIN:
        try:
            builtin = BuiltinField(key)
        except ValueError:
            raise _rule_error(f"unknown builtin field {key!r}") from None
        if op not in BUILTIN_OPS[builtin]:
            raise _rule_error(f'operator "{op}" does not apply to "{key}"')
        date_like = builtin in DATE_BUILTINS
        numeric = False
        params.pop("type", None)
        if builtin is BuiltinField.PRIORITY or builtin is BuiltinField.KIND:
            _validate_enum_values(builtin, params)
    else:
        definition = (definitions or {}).get(key)
        if definition is None:
            raise _rule_error(f"unknown custom field key(s): {key}")
        if op not in ops_for_field_type(definition.type):
            raise _rule_error(f'operator "{op}" does not apply to "{definition.name}"')
        # Snapshot the registry type — comparison + phrasing at evaluation time.
        params["type"] = str(definition.type)
        date_like = str(definition.type) == FieldType.DATE.value
        numeric = str(definition.type) in (FieldType.NUMBER.value, FieldType.DURATION.value)
        if str(definition.type) == FieldType.BOOLEAN.value:
            values = [str(v) for v in params.get("values") or []]
            if op is ConditionOp.IS and set(values) - {"true", "false"}:
                raise _rule_error(f'"{definition.name}" values must be true or false')
    values = [str(v) for v in params.get("values") or []]
    if op in (ConditionOp.SET, ConditionOp.EMPTY):
        params.pop("values", None)
        params.pop("display", None)
        return
    if op in (ConditionOp.IS, ConditionOp.IS_NOT) and not values:
        raise _rule_error("the condition needs at least one value")
    if op in (ConditionOp.GTE, ConditionOp.LTE):
        if len(values) != 1:
            raise _rule_error("the condition needs exactly one bound value")
        if date_like:
            _require_iso_date(values[0])
        elif numeric:
            _require_number(values[0])
    if numeric:
        for value in values:
            _require_number(value)
    if date_like:
        for value in values:
            _require_iso_date(value)


def _validate_enum_values(builtin: BuiltinField, params: dict) -> None:
    # Deferred: items loads after workflow (items depends_on workflow).
    from radd.modules.items.enums import ItemKind, Priority

    allowed = (
        {p.value for p in Priority}
        if builtin is BuiltinField.PRIORITY
        else {k.value for k in ItemKind}
    )
    bad = sorted({str(v) for v in params.get("values") or []} - allowed)
    if bad:
        raise _rule_error(f"unknown {builtin.value} value(s): {', '.join(bad)}")


def _require_iso_date(value: str) -> None:
    import datetime

    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        raise _rule_error(f"{value!r} is not a date (YYYY-MM-DD)") from None


def _require_number(value: str) -> None:
    try:
        float(value)
    except ValueError:
        raise _rule_error(f"{value!r} is not a number") from None


async def _validate_approval_rule(session: AsyncSession, params: dict) -> None:
    """Spec 107: per-entry approver rules — every entry names a real subject
    (users must be ACTIVE), team entries carry required >= 1, no duplicates.
    Display names are snapshotted server-side for guard failure strings."""
    from radd.modules.auth import service as auth
    from radd.modules.teams import service as teams_service

    entries = params.get("approvers")
    if not isinstance(entries, list) or not entries:
        raise _rule_error("an approval rule needs at least one approver")
    seen: set[tuple[str, str]] = set()
    user_ids: list[uuid.UUID] = []
    team_ids: list[uuid.UUID] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise _rule_error("malformed approver entry")
        try:
            kind = ApproverKind(entry.get("kind"))
            entry_id = uuid.UUID(str(entry.get("id")))
        except ValueError:
            raise _rule_error("malformed approver entry") from None
        if (kind.value, str(entry_id)) in seen:
            raise _rule_error("duplicate approver entry")
        seen.add((kind.value, str(entry_id)))
        if kind is ApproverKind.TEAM:
            required = entry.get("required", 1)
            if not isinstance(required, int) or isinstance(required, bool) or required < 1:
                raise _rule_error("a team's approvals required must be >= 1")
            team_ids.append(entry_id)
        else:
            entry.pop("required", None)  # meaningless on a person
            user_ids.append(entry_id)
    users = await auth.users_by_ids(session, user_ids) if user_ids else {}
    teams = await teams_service.teams_by_ids(session, team_ids) if team_ids else {}
    for entry in entries:
        entry_id = uuid.UUID(str(entry["id"]))
        if entry["kind"] == ApproverKind.USER.value:
            user = users.get(entry_id)
            if user is None or not user.active:
                raise _rule_error(f"unknown approver user {entry_id}")
            entry["name"] = user.name
        else:
            team = teams.get(entry_id)
            if team is None:
                raise _rule_error(f"unknown approver team {entry_id}")
            entry["name"] = team.name


async def create_transition(
    session: AsyncSession, data: TransitionCreate, actor_id: uuid.UUID | None = None
) -> WorkflowTransition:
    project = await projects_service.get_project(session, data.project_id)
    await _validate_edge(session, project.id, data.from_state_id, data.to_state_id)
    applies_when = [
        condition.model_dump(mode="json", exclude_none=True)
        for condition in data.applies_when
    ]
    await _validate_rules(session, project, data.rules, applies_when)
    if data.position is None:
        max_position = await session.scalar(
            select(func.max(WorkflowTransition.position)).where(
                WorkflowTransition.project_id == project.id
            )
        )
        position = (max_position or 0) + 1
    else:
        position = data.position
    transition = WorkflowTransition(
        project_id=project.id,
        from_state_id=data.from_state_id,
        to_state_id=data.to_state_id,
        rules=[rule.model_dump(mode="json") for rule in data.rules],
        applies_when=applies_when,
        position=position,
    )
    session.add(transition)
    await session.flush()
    await _emit(session, TransitionEvent.CREATED, transition, actor_id)
    return transition


async def update_transition(
    session: AsyncSession,
    transition_id: uuid.UUID,
    data: TransitionUpdate,
    actor_id: uuid.UUID | None = None,
) -> WorkflowTransition:
    transition = await get_transition(session, transition_id)
    project = await projects_service.get_project(session, transition.project_id)
    before = await _transition_audit_state(session, transition)
    # from_state_id: omitted = unchanged, explicit null = the wildcard.
    from_state_id = (
        data.from_state_id
        if "from_state_id" in data.model_fields_set
        else transition.from_state_id
    )
    to_state_id = data.to_state_id if data.to_state_id is not None else transition.to_state_id
    await _validate_edge(
        session, project.id, from_state_id, to_state_id, exclude_id=transition.id
    )
    if data.rules is not None:
        await _validate_rules(session, project, data.rules)
        transition.rules = [rule.model_dump(mode="json") for rule in data.rules]
    if data.applies_when is not None:
        applies_when = [
            condition.model_dump(mode="json", exclude_none=True)
            for condition in data.applies_when
        ]
        await _validate_rules(session, project, [], applies_when)
        transition.applies_when = applies_when
    transition.from_state_id = from_state_id
    transition.to_state_id = to_state_id
    if data.position is not None:
        transition.position = data.position
    await session.flush()
    await _emit(
        session,
        TransitionEvent.UPDATED,
        transition,
        actor_id,
        changes.diff(
            before,
            await _transition_audit_state(session, transition),
            collections=("rules", "applies_when"),
        ),
    )
    return transition


async def delete_transition(
    session: AsyncSession, transition_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    transition = await get_transition(session, transition_id)
    await projects_service.get_project(session, transition.project_id)
    await _emit(session, TransitionEvent.DELETED, transition, actor_id)
    await session.delete(transition)
    await session.flush()


# --- enforcement (the items seam) ---


async def resolve_mode(session: AsyncSession, project: Project) -> TransitionMode:
    return TransitionMode(
        await settings_service.resolve(
            session, SettingKey.WORKFLOW_TRANSITION_MODE, project_id=project.id
        )
    )


def edge_candidates(
    rows: Sequence[WorkflowTransition],
    from_state_id: uuid.UUID,
    to_state_id: uuid.UUID,
) -> list[WorkflowTransition]:
    """The rows that could govern (from, to), in resolution order: exact-from
    rows before from-NULL wildcards, each group keeping the list (position)
    order."""
    exact = [
        row
        for row in rows
        if row.to_state_id == to_state_id and row.from_state_id == from_state_id
    ]
    wildcards = [
        row
        for row in rows
        if row.to_state_id == to_state_id and row.from_state_id is None
    ]
    return exact + wildcards


def governing_row(
    candidates: Sequence[WorkflowTransition], snapshot: ItemSnapshot
) -> WorkflowTransition | None:
    """FIRST-MATCH resolution (spec 107 follow-up): the first candidate whose
    `applies_when` the ITEM satisfies governs the move, alone — so a specific
    row above a general one can both stack requirements and carve exemptions.
    Public — the approvals module (spec 71) resolves rules the same way."""
    for row in candidates:
        if guards.conditions_met(row.applies_when or [], snapshot):
            return row
    return None


async def snapshot_for(
    session: AsyncSession, project: Project, item, rows: Sequence[WorkflowTransition]
) -> ItemSnapshot:
    """The item snapshot covering every candidate row's needs — applies_when
    scoping AND rule evaluation (public: approvals resolves through it)."""
    all_rules = [rule for row in rows for rule in (row.rules or [])]
    all_conditions = [
        condition for row in rows for condition in (row.applies_when or [])
    ]
    return await _snapshot(session, project, item, all_rules, all_conditions)


async def governing_row_for(
    session: AsyncSession, project: Project, item, to_state_id: uuid.UUID
) -> WorkflowTransition | None:
    """The row governing THIS item's move to `to_state_id` (approvals'
    create-request seam)."""
    rows = await list_transitions(session, project.id)
    candidates = edge_candidates(rows, item.state_id, to_state_id)
    if not candidates:
        return None
    snapshot = await snapshot_for(session, project, item, candidates)
    return governing_row(candidates, snapshot)


def _maybe_str(value) -> str | None:
    return str(value) if value is not None else None


def _maybe_iso(value) -> str | None:
    return value.isoformat() if value is not None else None


async def _snapshot(
    session: AsyncSession,
    project: Project,
    item,
    rules: Sequence[dict],
    conditions: Sequence[dict] = (),
) -> ItemSnapshot:
    """Resolve only what the rules (and applies_when `conditions`) ask about
    (each lookup is a deferred import of the owning module's public seam —
    those modules load after workflow). The WorkItem columns are free;
    labels/estimate/comment cost a query each."""
    keys = guards.builtin_keys_in(rules) | guards.condition_builtin_keys(conditions)
    builtin: dict[str, object] = {
        BuiltinField.ASSIGNEE.value: _maybe_str(item.assignee_id),
        BuiltinField.REPORTER.value: _maybe_str(item.reporter_id),
        BuiltinField.TEAM.value: _maybe_str(item.team_id),
        BuiltinField.PRIORITY.value: item.priority,
        BuiltinField.KIND.value: item.kind,
        BuiltinField.TYPE.value: _maybe_str(item.type_id),
        BuiltinField.CYCLE.value: _maybe_str(item.cycle_id),
        BuiltinField.RELEASE.value: _maybe_str(item.release_id),
        BuiltinField.START_DATE.value: _maybe_iso(item.start_date),
        BuiltinField.TARGET_DATE.value: _maybe_iso(item.target_date),
    }
    if BuiltinField.LABELS.value in keys:
        # Deferred: items loads after workflow; the join table is items-owned.
        from radd.modules.items.models import ItemLabel

        label_ids = (
            await session.execute(
                select(ItemLabel.label_id).where(ItemLabel.item_id == item.id)
            )
        ).scalars()
        builtin[BuiltinField.LABELS.value] = [str(label_id) for label_id in label_ids]
    if BuiltinField.ESTIMATE.value in keys:
        from radd.modules.timelogging import service as timelogging

        builtin[BuiltinField.ESTIMATE.value] = (
            True if await timelogging.has_estimate(session, item.id) else None
        )
    if BuiltinField.COMMENT.value in keys:
        from radd.modules.comments import service as comments

        count = (await comments.comment_counts(session, [item.id])).get(item.id, 0)
        builtin[BuiltinField.COMMENT.value] = count or None
    field_labels: dict[str, str] = {}
    if guards.has_custom_conditions(rules) or guards.has_custom_condition(conditions):
        from radd.modules.fields import service as fields

        definitions = await fields.definitions_for_project(session, project)
        field_labels = {d.key: d.name for d in definitions}
    approved_to_state_ids: frozenset[str] = frozenset()
    if TransitionCheck.REQUIRE_APPROVAL in guards.checks_in(rules):
        # Spec 71: feature-detected — with the approvals module absent the rule
        # simply always fails (the editor hides the option then).
        try:
            from radd.modules.approvals import service as approvals_service
        except ImportError:
            pass
        else:
            approved_to_state_ids = frozenset(
                await approvals_service.approved_target_state_ids(session, item.id)
            )
    return ItemSnapshot(
        builtin=builtin,
        custom_fields=item.custom_fields or {},
        field_labels=field_labels,
        approved_to_state_ids=approved_to_state_ids,
    )


async def _state_names(
    session: AsyncSession, ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    result = await session.execute(select(State.id, State.name).where(State.id.in_(ids)))
    return dict(result.all())


async def check_transition(
    session: AsyncSession,
    project: Project,
    item,
    old_state_id: uuid.UUID,
    new_state_id: uuid.UUID,
) -> None:
    """Raise TransitionError when the project's mode/rules forbid this state
    change. Called by items.update_item AFTER the patch is applied (so values in
    the same PATCH count) and only on a REAL state change. Applies to every actor
    including automations/SYSTEM (predictability over convenience)."""
    mode = await resolve_mode(session, project)
    if mode is TransitionMode.OFF:
        return
    rows = await list_transitions(session, project.id)
    candidates = edge_candidates(rows, old_state_id, new_state_id)
    if not candidates:
        if mode is TransitionMode.STRICT and rows:
            names = await _state_names(session, {old_state_id, new_state_id})
            from_name = names.get(old_state_id, "?")
            to_name = names.get(new_state_id, "?")
            raise TransitionError(
                [f'no transition from "{from_name}" to "{to_name}" is defined'],
                from_name,
                to_name,
            )
        return
    snapshot = await snapshot_for(session, project, item, candidates)
    row = governing_row(candidates, snapshot)
    if row is None:
        # Rows exist for the edge but none applies to THIS item (spec 107
        # follow-up): guards frees the move, strict blocks it.
        if mode is TransitionMode.STRICT:
            names = await _state_names(session, {old_state_id, new_state_id})
            from_name = names.get(old_state_id, "?")
            to_name = names.get(new_state_id, "?")
            raise TransitionError(
                [f'no transition from "{from_name}" to "{to_name}" applies to this item'],
                from_name,
                to_name,
            )
        return
    if not row.rules:
        return
    failures = guards.evaluate(row.rules, snapshot, to_state_id=str(new_state_id))
    if failures:
        names = await _state_names(session, {old_state_id, new_state_id})
        raise TransitionError(
            failures, names.get(old_state_id, "?"), names.get(new_state_id, "?")
        )


async def allowed_transitions(
    session: AsyncSession, project: Project, item
) -> AllowedTransitions:
    """Every project state as a target from the item's CURRENT state — the state
    pickers' graying/tooltip source. `off` -> everything allowed."""
    states = (
        await session.execute(
            select(State).where(State.project_id == project.id).order_by(State.position)
        )
    ).scalars()
    mode = await resolve_mode(session, project)
    targets: list[AllowedTarget] = []
    if mode is TransitionMode.OFF:
        return AllowedTransitions(
            mode=mode,
            targets=[AllowedTarget(state_id=s.id, allowed=True, failures=[]) for s in states],
        )
    rows = await list_transitions(session, project.id)
    snapshot = await snapshot_for(session, project, item, rows)
    for state in states:
        if state.id == item.state_id:
            # Staying put is not a transition — trivially allowed.
            targets.append(AllowedTarget(state_id=state.id, allowed=True, failures=[]))
            continue
        candidates = edge_candidates(rows, item.state_id, state.id)
        row = governing_row(candidates, snapshot) if candidates else None
        if row is None:
            if mode is TransitionMode.STRICT and rows:
                failures = (
                    [f'no transition to "{state.name}" applies to this item']
                    if candidates
                    else [f'no transition to "{state.name}" is defined']
                )
            else:
                failures = []
        else:
            failures = guards.evaluate(row.rules, snapshot, to_state_id=str(state.id))
        targets.append(
            AllowedTarget(state_id=state.id, allowed=not failures, failures=failures)
        )
    return AllowedTransitions(mode=mode, targets=targets)


async def _transition_audit_state(
    session: AsyncSession, transition: WorkflowTransition
) -> dict:
    """What a transition diff can mention (spec 123): state NAMES, the rule and
    condition lists (diffed as added/removed entries), the position."""
    names = await _state_names(
        session,
        {sid for sid in (transition.from_state_id, transition.to_state_id) if sid},
    )
    return {
        "from_state": names.get(transition.from_state_id),
        "to_state": names.get(transition.to_state_id),
        "rules": transition.rules,
        "applies_when": transition.applies_when,
        "position": transition.position,
    }


async def _emit(
    session: AsyncSession,
    event_type: TransitionEvent,
    transition: WorkflowTransition,
    actor_id: uuid.UUID | None,
    diff: list[dict] | None = None,
) -> None:
    names = await _state_names(
        session,
        {sid for sid in (transition.from_state_id, transition.to_state_id) if sid},
    )
    await events.emit(
        session,
        event_type=event_type,
        entity_type=TransitionEntity.TRANSITION,
        entity_id=transition.id,
        actor_id=actor_id,
        payload={
            "project_id": str(transition.project_id),
            "from_state": names.get(transition.from_state_id),
            "to_state": names.get(transition.to_state_id),
            "rules": transition.rules,
            "applies_when": transition.applies_when,
        },
        subjects={"project": transition.project_id},
        changes=diff,
    )
