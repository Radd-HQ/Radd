"""Spec 119: intake validation as an automation graph.

The claims under test are the ones the rest of the feature stands on:

* a VALIDATE trigger is indexed into `automation_validations` the way an event
  trigger is indexed into `automation_triggers` — rebuilt wholesale, so removing
  a target removes the governance;
* resolution UNIONS the three axes (project, issue type, form) and never runs one
  graph twice for a draft that matches it on two of them;
* the walk collects findings and APPLIES NOTHING — the action that would have
  labelled the draft did not;
* the write path refuses a trigger that governs nothing and a check that says
  nothing, because both of those store as "configured" and then do nothing at all.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as app_settings
from radd.exceptions import ConflictError
from radd.modules.automations import service as automations_service, validation
from radd.modules.automations.models import ValidationBinding
from radd.modules.automations.schemas import RuleCreate, RuleUpdate
from radd.modules.automations.types import (
    TYPE_VALIDATION_FAIL,
    AutomationTrigger,
    ValidationMode,
    ValidationTargetKind,
)
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.itemtypes import service as itemtypes_service
from radd.modules.itemtypes.schemas import IssueTypeCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(app_settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"iv-{uuid.uuid4().hex[:8]}@example.com",
        name="Intake admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def project(db):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"IV{uuid.uuid4().hex[:4].upper()}", name="Intake validation")
    )


def _validate_trigger(targets: list[dict], mode: str = ValidationMode.ADVISORY.value) -> dict:
    return {
        "id": "trg",
        "kind": "trigger",
        "type": "trigger.event",
        "params": {"event": AutomationTrigger.VALIDATE.value, "targets": targets, "mode": mode},
    }


def _fail_node(node_id: str, message: str, field: str = "") -> dict:
    return {
        "id": node_id,
        "kind": "action",
        "type": TYPE_VALIDATION_FAIL,
        "params": {"message": message, "field": field},
    }


async def _graph(db, admin, *, targets, mode=ValidationMode.ADVISORY.value, nodes=(), edges=(),
                 name="checks", enabled=True):
    return await automations_service.create_rule(
        db,
        RuleCreate(
            name=f"{name}-{uuid.uuid4().hex[:6]}",
            enabled=enabled,
            nodes=[_validate_trigger(targets, mode), *nodes],
            edges=list(edges),
        ),
        actor_id=admin.id,
    )


async def _bindings(db, automation_id) -> list[ValidationBinding]:
    rows = await db.execute(
        select(ValidationBinding).where(ValidationBinding.automation_id == automation_id)
    )
    return list(rows.scalars())


# --- pure parsing -------------------------------------------------------------


def test_targets_parse_into_typed_rows_and_deduplicate():
    form_id, project_id = uuid.uuid4(), uuid.uuid4()
    parsed = validation.parse_targets(
        {
            "targets": [
                {"kind": "form", "id": str(form_id)},
                {"kind": "form", "id": str(form_id)},  # the same target twice
                {"kind": "project", "id": str(project_id)},
            ]
        }
    )
    assert parsed == [
        validation.ValidationTarget(ValidationTargetKind.FORM, form_id),
        validation.ValidationTarget(ValidationTargetKind.PROJECT, project_id),
    ]


def test_unreadable_targets_degrade_rather_than_raise():
    """A departed target is a binding that stops matching, not a graph that
    refuses to load — the same rule a card layout's deleted attribute follows.
    The WRITE path is where a malformed target is refused."""
    assert validation.parse_targets({"targets": [{"kind": "galaxy", "id": str(uuid.uuid4())}]}) == []
    assert validation.parse_targets({"targets": [{"kind": "form", "id": "not-a-uuid"}]}) == []
    assert validation.parse_targets({"targets": ["nope", None, 7]}) == []
    assert validation.parse_targets({}) == []


def test_mode_defaults_to_advisory_and_strictest_wins():
    assert validation.parse_mode({}) is ValidationMode.ADVISORY
    assert validation.parse_mode({"mode": "nonsense"}) is ValidationMode.ADVISORY
    assert validation.parse_mode({"mode": "required"}) is ValidationMode.REQUIRED
    assert validation.strictest([]) is ValidationMode.ADVISORY
    assert (
        validation.strictest([ValidationMode.ADVISORY, ValidationMode.REQUIRED])
        is ValidationMode.REQUIRED
    )


# --- the index ----------------------------------------------------------------


async def test_a_validate_trigger_is_indexed_per_target(db, admin, project):
    type_id = uuid.uuid4()
    rule = await _graph(
        db,
        admin,
        targets=[
            {"kind": "project", "id": str(project.id)},
            {"kind": "issue_type", "id": str(type_id)},
        ],
        mode=ValidationMode.REQUIRED.value,
        nodes=[_fail_node("chk", "Say more.")],
        edges=[{"source": "trg", "port": "out", "target": "chk"}],
    )
    rows = await _bindings(db, rule.id)
    assert {(row.target_kind, row.target_id) for row in rows} == {
        (ValidationTargetKind.PROJECT.value, project.id),
        (ValidationTargetKind.ISSUE_TYPE.value, type_id),
    }
    assert {row.mode for row in rows} == {ValidationMode.REQUIRED.value}


async def test_dropping_a_target_drops_its_governance(db, admin, project):
    """Rebuilt wholesale, never diffed: a surviving row is a form governed by a
    check nobody can see on the canvas."""
    other = uuid.uuid4()
    rule = await _graph(
        db,
        admin,
        targets=[{"kind": "project", "id": str(project.id)}, {"kind": "form", "id": str(other)}],
        nodes=[_fail_node("chk", "Say more.")],
        edges=[{"source": "trg", "port": "out", "target": "chk"}],
    )
    assert len(await _bindings(db, rule.id)) == 2

    await automations_service.update_rule(
        db,
        rule.id,
        RuleUpdate(
            nodes=[
                _validate_trigger([{"kind": "project", "id": str(project.id)}]),
                _fail_node("chk", "Say more."),
            ],
            edges=[{"source": "trg", "port": "out", "target": "chk"}],
        ),
        actor_id=admin.id,
    )
    rows = await _bindings(db, rule.id)
    assert [(row.target_kind, row.target_id) for row in rows] == [
        (ValidationTargetKind.PROJECT.value, project.id)
    ]


async def test_a_graph_with_no_validate_trigger_indexes_nothing(db, admin):
    rule = await automations_service.create_rule(
        db,
        RuleCreate(
            name=f"ordinary-{uuid.uuid4().hex[:6]}",
            nodes=[
                {"id": "trg", "kind": "trigger", "type": "trigger.event",
                 "params": {"event": "item.created"}},
                {"id": "a", "kind": "action", "type": "action.add_label",
                 "params": {"label": "new"}},
            ],
            edges=[{"source": "trg", "port": "out", "target": "a"}],
        ),
        actor_id=admin.id,
    )
    assert await _bindings(db, rule.id) == []


# --- write-path refusals ------------------------------------------------------


async def test_a_validate_trigger_with_no_targets_is_refused(db, admin):
    """It would sit in the list looking configured and never once run."""
    with pytest.raises(ConflictError, match="at least one target"):
        await _graph(db, admin, targets=[])


async def test_an_unknown_target_kind_is_refused(db, admin, project):
    with pytest.raises(ConflictError, match="unknown target kind"):
        await _graph(db, admin, targets=[{"kind": "galaxy", "id": str(project.id)}])


async def test_a_bad_mode_is_refused(db, admin, project):
    with pytest.raises(ConflictError, match="mode must be"):
        await _graph(
            db, admin, targets=[{"kind": "project", "id": str(project.id)}], mode="whenever"
        )


async def test_a_check_with_no_message_is_refused(db, admin, project):
    with pytest.raises(ConflictError, match="needs a message"):
        await _graph(
            db,
            admin,
            targets=[{"kind": "project", "id": str(project.id)}],
            nodes=[_fail_node("chk", "")],
            edges=[{"source": "trg", "port": "out", "target": "chk"}],
        )


async def test_a_check_may_only_target_a_real_field_shape(db, admin, project):
    with pytest.raises(ConflictError, match="is not a field"):
        await _graph(
            db,
            admin,
            targets=[{"kind": "project", "id": str(project.id)}],
            nodes=[_fail_node("chk", "Pick one.", field="severity")],
            edges=[{"source": "trg", "port": "out", "target": "chk"}],
        )


async def test_builtin_and_custom_field_shapes_are_accepted(db, admin, project):
    rule = await _graph(
        db,
        admin,
        targets=[{"kind": "project", "id": str(project.id)}],
        nodes=[
            _fail_node("a", "Describe it.", field="description"),
            _fail_node("b", "Pick a severity.", field="cf.severity"),
        ],
        edges=[
            {"source": "trg", "port": "out", "target": "a"},
            {"source": "a", "port": "out", "target": "b"},
        ],
    )
    assert len(await _bindings(db, rule.id)) == 1


# --- resolution ---------------------------------------------------------------


async def test_resolution_unions_the_axes_without_running_a_graph_twice(db, admin, project):
    """A project-wide rule and a form-specific one both apply; a graph that
    matches on BOTH axes still runs once."""
    form_id = uuid.uuid4()
    both = await _graph(
        db,
        admin,
        targets=[
            {"kind": "project", "id": str(project.id)},
            {"kind": "form", "id": str(form_id)},
        ],
        mode=ValidationMode.ADVISORY.value,
        nodes=[_fail_node("chk", "hello")],
        edges=[{"source": "trg", "port": "out", "target": "chk"}],
    )
    elsewhere = await _graph(
        db,
        admin,
        targets=[{"kind": "project", "id": str(uuid.uuid4())}],
        nodes=[_fail_node("chk", "not this one")],
        edges=[{"source": "trg", "port": "out", "target": "chk"}],
    )
    scope = validation.DraftScope(project_id=project.id, form_id=form_id)
    found = await validation.governing_graphs(db, scope)
    ids = [g.automation.id for g in found]
    assert ids.count(both.id) == 1
    assert elsewhere.id not in ids


async def test_a_disabled_automation_governs_nothing(db, admin, project):
    await _graph(
        db,
        admin,
        targets=[{"kind": "project", "id": str(project.id)}],
        enabled=False,
        nodes=[_fail_node("chk", "hello")],
        edges=[{"source": "trg", "port": "out", "target": "chk"}],
    )
    scope = validation.DraftScope(project_id=project.id)
    assert await validation.governing_graphs(db, scope) == []


async def test_required_only_narrows_to_the_enforcing_bindings(db, admin, project):
    advisory = await _graph(
        db,
        admin,
        targets=[{"kind": "project", "id": str(project.id)}],
        mode=ValidationMode.ADVISORY.value,
        nodes=[_fail_node("chk", "advice")],
        edges=[{"source": "trg", "port": "out", "target": "chk"}],
    )
    required = await _graph(
        db,
        admin,
        targets=[{"kind": "project", "id": str(project.id)}],
        mode=ValidationMode.REQUIRED.value,
        nodes=[_fail_node("chk", "law")],
        edges=[{"source": "trg", "port": "out", "target": "chk"}],
    )
    scope = validation.DraftScope(project_id=project.id)
    ids = [g.automation.id for g in await validation.governing_graphs(db, scope, required_only=True)]
    assert required.id in ids and advisory.id not in ids


# --- the walk -----------------------------------------------------------------


async def _draft(db, project, admin, title="a draft"):
    return await items_service.create_item(
        db, ItemCreate(project_id=project.id, title=title), actor=admin
    )


async def test_the_walk_collects_findings_and_applies_nothing(db, admin, project):
    """The action node is in the graph and reachable; a validation walk must not
    have run it. That is `apply=False`, not a second walker."""
    await _graph(
        db,
        admin,
        targets=[{"kind": "project", "id": str(project.id)}],
        nodes=[
            _fail_node("chk", "Add steps to reproduce.", field="description"),
            {"id": "lbl", "kind": "action", "type": "action.add_label",
             "params": {"label": "validated"}},
        ],
        edges=[
            {"source": "trg", "port": "out", "target": "chk"},
            {"source": "chk", "port": "out", "target": "lbl"},
        ],
    )
    draft = await _draft(db, project, admin)
    scope = validation.DraftScope(project_id=project.id)
    verdict = await validation.run_graphs(
        db, draft.id, scope, await validation.governing_graphs(db, scope)
    )

    assert verdict.governed is True
    assert verdict.passed is False
    assert [(f.field, f.message) for f in verdict.findings] == [
        ("description", "Add steps to reproduce.")
    ]
    # The label action was downstream of the check and reachable — and it did
    # not run, because a validation walk plans without applying.
    after = await items_service.get_item(db, draft.id, admin)
    assert after.labels == []


async def test_a_filter_that_matches_nothing_produces_no_findings(db, admin, project):
    """Condition-based applicability needs no params on the trigger: the GRAPH
    expresses it, and an unmatched packet simply reaches no check."""
    await _graph(
        db,
        admin,
        targets=[{"kind": "project", "id": str(project.id)}],
        nodes=[
            {"id": "f", "kind": "filter", "type": "filter.slq",
             "params": {"slq": "priority = blocker"}},
            _fail_node("chk", "Blockers need an assignee.", field="assignee"),
        ],
        edges=[
            {"source": "trg", "port": "out", "target": "f"},
            {"source": "f", "port": "matched", "target": "chk"},
        ],
    )
    draft = await _draft(db, project, admin)  # normal priority
    scope = validation.DraftScope(project_id=project.id)
    verdict = await validation.run_graphs(
        db, draft.id, scope, await validation.governing_graphs(db, scope)
    )
    assert verdict.passed is True
    assert verdict.governed is True


async def test_no_governing_graph_is_not_the_same_as_a_clean_pass(db, admin, project):
    draft = await _draft(db, project, admin)
    scope = validation.DraftScope(project_id=project.id)
    verdict = await validation.run_graphs(db, draft.id, scope, [])
    assert verdict.governed is False
    assert verdict.passed is True


async def test_findings_from_several_graphs_concatenate_and_the_strictest_mode_wins(
    db, admin, project
):
    for mode, message in (
        (ValidationMode.ADVISORY.value, "Consider adding a screenshot."),
        (ValidationMode.REQUIRED.value, "A severity is required."),
    ):
        await _graph(
            db,
            admin,
            targets=[{"kind": "project", "id": str(project.id)}],
            mode=mode,
            nodes=[_fail_node("chk", message)],
            edges=[{"source": "trg", "port": "out", "target": "chk"}],
        )
    draft = await _draft(db, project, admin)
    scope = validation.DraftScope(project_id=project.id)
    verdict = await validation.run_graphs(
        db, draft.id, scope, await validation.governing_graphs(db, scope)
    )
    assert sorted(f.message for f in verdict.findings) == [
        "A severity is required.",
        "Consider adding a screenshot.",
    ]
    assert verdict.mode is ValidationMode.REQUIRED
    assert verdict.blocks is True


async def test_an_issue_type_target_governs_only_that_type(db, admin, project):
    bug = await itemtypes_service.create_type(
        db,
        IssueTypeCreate(
            project_id=project.id, name=f"Defect {uuid.uuid4().hex[:6]}", color="#ff0000"
        ),
        actor_id=admin.id,
    )
    await _graph(
        db,
        admin,
        targets=[{"kind": "issue_type", "id": str(bug.id)}],
        nodes=[_fail_node("chk", "Bugs need repro steps.", field="description")],
        edges=[{"source": "trg", "port": "out", "target": "chk"}],
    )
    typed = validation.DraftScope(project_id=project.id, type_id=bug.id)
    untyped = validation.DraftScope(project_id=project.id, type_id=uuid.uuid4())
    assert len(await validation.governing_graphs(db, typed)) == 1
    assert await validation.governing_graphs(db, untyped) == []
