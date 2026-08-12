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
from radd.modules.automations import intake, service as automations_service, validation
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
from radd.modules.events import service as events
from radd.modules.items import service as items_service
from radd.modules.items.models import WorkItem
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
    # The draft is created BEFORE the required graph exists — otherwise the
    # spec-119 hook would (correctly) refuse this very create. That the plain
    # helper cannot make an item once a required check governs the project is
    # the enforcement working, and it has its own test below.
    draft = await _draft(db, project, admin)
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


# --- the savepoint flow (RADD-1058) -------------------------------------------


async def _required_graph(db, admin, project, message="A severity is required.", field=""):
    return await _graph(
        db,
        admin,
        targets=[{"kind": "project", "id": str(project.id)}],
        mode=ValidationMode.REQUIRED.value,
        nodes=[_fail_node("chk", message, field)],
        edges=[{"source": "trg", "port": "out", "target": "chk"}],
    )


async def _advisory_graph(db, admin, project, message="Consider adding a screenshot."):
    return await _graph(
        db,
        admin,
        targets=[{"kind": "project", "id": str(project.id)}],
        mode=ValidationMode.ADVISORY.value,
        nodes=[_fail_node("chk", message)],
        edges=[{"source": "trg", "port": "out", "target": "chk"}],
    )


async def _count_items(db, project_id: uuid.UUID) -> int:
    """Takes the ID, not the ORM row, and that is not fussiness.

    Rolling back a SAVEPOINT expires the states it touched, and reading an
    expired attribute from SYNCHRONOUS code — which is what `project.id` inside
    a `select(...)` builder is — attempts IO outside the greenlet context and
    raises `MissingGreenlet`. Every call site in the app reads only the verdict
    after a rollback, so nothing is exposed to this; a test that holds the row
    across the flow is, and would report it as a product bug."""
    rows = await db.execute(select(WorkItem.id).where(WorkItem.project_id == project_id))
    return len(list(rows.scalars()))


async def test_a_failing_draft_leaves_nothing_behind(db, admin, project):
    """The savepoint is the whole design: the row that was validated is a REAL
    row, and a failed one is taken back with its `item.created` event."""
    await _advisory_graph(db, admin, project)
    project_id = project.id
    before = await _count_items(db, project_id)
    outcome = await intake.validate_and_create(
        db, ItemCreate(project_id=project_id, title="thin"), admin
    )
    assert outcome.created is None
    assert outcome.verdict.passed is False
    assert await _count_items(db, project_id) == before


async def test_a_clean_draft_is_kept_in_the_same_round_trip(db, admin, project):
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
    outcome = await intake.validate_and_create(
        db, ItemCreate(project_id=project.id, title="ordinary"), admin
    )
    assert outcome.created is not None
    assert outcome.verdict.passed is True
    assert (await items_service.get_item(db, outcome.created.id, admin)).title == "ordinary"


async def test_create_anyway_keeps_an_advisory_draft_with_its_findings(db, admin, project):
    await _advisory_graph(db, admin, project)
    outcome = await intake.validate_and_create(
        db,
        ItemCreate(project_id=project.id, title="thin"),
        admin,
        commit=intake.IntakeCommit.ALWAYS,
    )
    assert outcome.created is not None
    # The findings still come back — the person chose to proceed past them, and
    # a caller that shows them anyway is showing the truth.
    assert [f.message for f in outcome.verdict.findings] == ["Consider adding a screenshot."]


async def test_create_anyway_is_refused_where_the_checks_are_required(db, admin, project):
    """A mode the admin chose is not something a request parameter overrules."""
    await _required_graph(db, admin, project)
    project_id = project.id
    before = await _count_items(db, project_id)
    with pytest.raises(ConflictError, match="required mode"):
        await intake.validate_and_create(
            db,
            ItemCreate(project_id=project_id, title="thin"),
            admin,
            commit=intake.IntakeCommit.ALWAYS,
        )
    assert await _count_items(db, project_id) == before


async def test_never_creates_nothing_even_on_a_clean_draft(db, admin, project):
    await _advisory_graph(db, admin, project)
    project_id = project.id
    before = await _count_items(db, project_id)
    outcome = await intake.validate_and_create(
        db,
        ItemCreate(project_id=project_id, title="thin"),
        admin,
        commit=intake.IntakeCommit.NEVER,
    )
    assert outcome.created is None
    assert await _count_items(db, project_id) == before


async def test_an_ordinary_create_failure_leaves_the_transaction_usable(db, admin, project):
    """A savepoint that is not rolled back on the way out poisons every later
    statement in the request — so an authz/validation refusal has to unwind it."""
    project_id = project.id
    with pytest.raises(Exception):
        await intake.validate_and_create(
            db, ItemCreate(project_id=uuid.uuid4(), title="nowhere"), admin
        )
    # The session still works.
    assert await _count_items(db, project_id) >= 0


# --- enforcement for every other caller ---------------------------------------


async def test_a_required_check_refuses_a_plain_create(db, admin, project):
    """`POST /items`, MCP, an extension, a script — the hook is what makes a
    required rule a rule rather than a suggestion with a nice interface."""
    await _required_graph(db, admin, project)
    with pytest.raises(intake.ValidationBlocked) as raised:
        await items_service.create_item(
            db, ItemCreate(project_id=project.id, title="straight in"), actor=admin
        )
    assert [f.message for f in raised.value.findings] == ["A severity is required."]


async def test_an_advisory_check_never_taxes_the_api_path(db, admin, project):
    """Advisory findings have nowhere to go on this path — no one to show them
    to and nothing they would change — so the plain create is untouched."""
    await _advisory_graph(db, admin, project)
    created = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="straight in"), actor=admin
    )
    assert created.title == "straight in"


async def test_the_engine_s_own_creations_are_not_intake(db, admin, project):
    """An automation's output is not somebody submitting a request, and a
    required check that refused it would break the automation."""
    await _required_graph(db, admin, project)
    with events.automated():
        created = await items_service.create_item(
            db, ItemCreate(project_id=project.id, title="made by a rule"), actor=admin
        )
    assert created.title == "made by a rule"


async def test_an_import_is_not_intake(db, admin, project):
    """Validating historical rows would refuse to import exactly the
    badly-filled-in issues the checks exist to stop being created today."""
    await _required_graph(db, admin, project)
    with events.quiet():
        created = await items_service.create_item(
            db, ItemCreate(project_id=project.id, title="from Jira"), actor=admin
        )
    assert created.title == "from Jira"


async def test_the_savepoint_flow_does_not_validate_twice(db, admin, project):
    """Its inner create goes through the same `create_item` the hook watches;
    without the suppress scope every finding would arrive in duplicate."""
    await _required_graph(db, admin, project)
    outcome = await intake.validate_and_create(
        db, ItemCreate(project_id=project.id, title="thin"), admin
    )
    assert outcome.created is None
    assert [f.message for f in outcome.verdict.findings] == ["A severity is required."]
    assert intake.is_suppressed() is False  # the scope closed


async def test_the_context_read_is_resolution_only(db, admin, project):
    assert await intake.context_for(db, validation.DraftScope(project_id=project.id)) == (
        False,
        None,
    )
    await _advisory_graph(db, admin, project)
    assert await intake.context_for(db, validation.DraftScope(project_id=project.id)) == (
        True,
        ValidationMode.ADVISORY,
    )
    await _required_graph(db, admin, project)
    assert await intake.context_for(db, validation.DraftScope(project_id=project.id)) == (
        True,
        ValidationMode.REQUIRED,
    )


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


# --- the contributed-node seam, end to end (RADD-1059) ------------------------


async def test_the_ai_node_contributes_findings_through_the_real_walk(
    db, admin, project, monkeypatch
):
    """`ctx.add_finding` is the seam a node in ANOTHER module reaches the
    collection through, and this is the only test that exercises it with the
    real `_NodeContext` rather than a stand-in. The provider is mocked; the
    field vocabulary is resolved against the live registry on purpose, so the
    unknown-key degradation is proven against real data.
    """
    from radd.modules.ai import automation_node_validate as ai_validate

    async def _enabled(_session, _feature):
        return True

    async def _ask(_ctx, _params):
        return {
            "passed": False,
            "findings": [
                {"message": "Say what you expected to happen.", "field": "description"},
                {"message": "Which module is this in?", "field": "cf.module_that_left"},
            ],
        }

    monkeypatch.setattr("radd.modules.ai.features.feature_enabled", _enabled)
    monkeypatch.setattr(ai_validate, "_ask", _ask)

    await _graph(
        db,
        admin,
        targets=[{"kind": "project", "id": str(project.id)}],
        nodes=[
            {
                "id": "ai",
                "kind": "gate",
                "type": "ai.validate",
                "params": {"prompt": "A report must say what was expected."},
            }
        ],
        edges=[{"source": "trg", "port": "out", "target": "ai"}],
    )
    draft = await _draft(db, project, admin, title="thin")
    scope = validation.DraftScope(project_id=project.id)
    verdict = await validation.run_graphs(
        db, draft.id, scope, await validation.governing_graphs(db, scope)
    )
    assert verdict.passed is False
    assert [(f.field, f.message) for f in verdict.findings] == [
        ("description", "Say what you expected to happen."),
        # The custom field does not exist in this project, so the advice keeps
        # its words and loses its control.
        ("", "Which module is this in?"),
    ]
    # Every finding still names the node that produced it.
    assert {f.node_id for f in verdict.findings} == {"ai"}


async def test_an_ai_outage_does_not_block_intake(db, admin, project, monkeypatch):
    """The whole feature's worst failure mode, wired end to end: a provider that
    is down must not turn a REQUIRED intake into a refused one."""
    from radd.modules.ai import automation_node_validate as ai_validate

    async def _boom(_ctx, _params):
        raise RuntimeError("connection refused")

    async def _enabled(_session, _feature):
        return True

    monkeypatch.setattr("radd.modules.ai.features.feature_enabled", _enabled)
    monkeypatch.setattr(ai_validate, "_ask", _boom)

    await _graph(
        db,
        admin,
        targets=[{"kind": "project", "id": str(project.id)}],
        mode=ValidationMode.REQUIRED.value,
        nodes=[
            {
                "id": "ai",
                "kind": "gate",
                "type": "ai.validate",
                "params": {"prompt": "A report must say what was expected."},
            }
        ],
        edges=[{"source": "trg", "port": "out", "target": "ai"}],
    )
    outcome = await intake.validate_and_create(
        db, ItemCreate(project_id=project.id, title="thin"), admin
    )
    assert outcome.created is not None
    assert outcome.verdict.passed is True


async def test_an_ai_node_with_no_prompt_is_refused_on_write(db, admin, project):
    """Its `params_schema` marks `prompt` required, and `_check_node_schema`
    enforces a contributed node's own schema where the automation is WRITTEN."""
    with pytest.raises(ConflictError, match="'prompt' is required"):
        await _graph(
            db,
            admin,
            targets=[{"kind": "project", "id": str(project.id)}],
            nodes=[{"id": "ai", "kind": "gate", "type": "ai.validate", "params": {"prompt": ""}}],
            edges=[{"source": "trg", "port": "out", "target": "ai"}],
        )


# --- the endpoints, over the assembled app (RADD-761's lesson) ----------------
#
# A route that registers, appears in the OpenAPI schema and is never CALLED is
# how `/pages/search` spent a release answering a 422 about parsing "search" as a
# UUID. These two live in `automations` under an `/items` prefix, mounted AFTER
# the items router — the only thing that makes them reachable is that a
# method-mismatched path is a PARTIAL match Starlette replaces with a later FULL
# one. That is a property of the framework, not of this code, so it is probed
# rather than reasoned about.


@pytest.fixture(scope="module")
async def http_world():
    """COMMITTED: the app under test opens its own sessions."""
    from radd.modules.auth import service as auth_service

    engine = create_async_engine(app_settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        admin = User(
            email=f"ivh-{uuid.uuid4().hex[:8]}@example.com",
            name="Intake HTTP",
            instance_role=InstanceRole.ADMIN.value,
        )
        session.add(admin)
        await session.flush()
        cookie = await auth_service.create_session(session, admin)
        project = await projects_service.create_project(
            session,
            ProjectCreate(key=f"IH{uuid.uuid4().hex[:4].upper()}", name="Intake HTTP"),
            actor_id=admin.id,
        )
        await automations_service.create_rule(
            session,
            RuleCreate(
                name=f"http-checks-{uuid.uuid4().hex[:6]}",
                nodes=[
                    _validate_trigger(
                        [{"kind": "project", "id": str(project.id)}],
                        ValidationMode.REQUIRED.value,
                    ),
                    _fail_node("chk", "Describe what you expected.", field="description"),
                ],
                edges=[{"source": "trg", "port": "out", "target": "chk"}],
            ),
            actor_id=admin.id,
        )
        payload = {"cookie": cookie, "project_id": str(project.id)}
        await session.commit()
        yield payload
    await engine.dispose()


@pytest.fixture(scope="module")
def intake_app():
    from radd.app import create_app

    return create_app()


@pytest.fixture
async def intake_client(intake_app):
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=intake_app), base_url="http://test"
    ) as client:
        yield client


async def test_the_validate_endpoint_is_reachable_and_answers_with_a_verdict(
    intake_client, http_world
):
    from radd.modules.auth.types import SESSION_COOKIE_NAME

    cookies = {SESSION_COOKIE_NAME: http_world["cookie"]}
    response = await intake_client.post(
        "/api/v1/items/validate",
        json={"project_id": http_world["project_id"], "title": "no detail"},
        cookies=cookies,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] is None
    assert body["verdict"]["governed"] is True
    assert body["verdict"]["mode"] == "required"
    assert body["verdict"]["findings"] == [
        {"message": "Describe what you expected.", "field": "description", "node_id": "chk"}
    ]


async def test_the_context_read_is_reachable_behind_the_item_id_route(intake_client, http_world):
    """Three segments on purpose: `GET /items/validation-context` would have sat
    behind `GET /items/{item_id}` and 422'd about parsing a word as a UUID."""
    from radd.modules.auth.types import SESSION_COOKIE_NAME

    response = await intake_client.get(
        "/api/v1/items/validate/context",
        params={"project_id": http_world["project_id"]},
        cookies={SESSION_COOKIE_NAME: http_world["cookie"]},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"governed": True, "mode": "required"}


async def test_a_plain_post_items_gets_the_third_422_vocabulary(intake_client, http_world):
    """`{detail, findings}` — not `errors`, which already means two other things."""
    from radd.modules.auth.types import SESSION_COOKIE_NAME

    response = await intake_client.post(
        "/api/v1/items",
        json={"project_id": http_world["project_id"], "title": "straight in"},
        cookies={SESSION_COOKIE_NAME: http_world["cookie"]},
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["detail"] == "item validation failed"
    assert body["mode"] == "required"
    assert [f["field"] for f in body["findings"]] == ["description"]


async def test_the_mcp_create_item_tool_relays_a_readable_refusal(db, admin, project):
    """Verified, not rebuilt: the MCP dispatcher already turns any `RaddError`
    into an `isError` result carrying `str(exc)`, so what matters is that
    `ValidationBlocked` IS one and that stringifying it says something a person
    (or an agent) can act on — not "ValidationBlocked()"."""
    from radd.exceptions import RaddError
    from radd.modules.mcp.router import _TOOL_ERROR_TYPES

    await _required_graph(db, admin, project, "A severity is required.")
    with pytest.raises(intake.ValidationBlocked) as raised:
        await items_service.create_item(
            db, ItemCreate(project_id=project.id, title="via mcp"), actor=admin
        )
    assert isinstance(raised.value, RaddError)
    assert isinstance(raised.value, _TOOL_ERROR_TYPES)
    assert str(raised.value) == "A severity is required."
