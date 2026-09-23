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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as app_settings
from radd.exceptions import ConflictError
from radd.modules.automations import (
    engine,
    executor,
    intake,
    service as automations_service,
    validation,
)
from radd.modules.automations.intake_schemas import verdict_read
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
from radd.modules.auth.types import LoginMethod


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


async def test_an_event_gate_under_a_validate_trigger_is_refused(db, admin, project):
    """There is no event. `gate.field_changed` reads a diff a submission does not
    have, so it answers a constant — and the branch behind the port it never
    takes is a check that looks configured and can never run. The same reasoning
    that refuses a gate under a SCHEDULE trigger, which is where the precedent
    is; it was simply never extended to this third sentinel.
    """
    with pytest.raises(ConflictError, match="has no event"):
        await _graph(
            db,
            admin,
            targets=[{"kind": "project", "id": str(project.id)}],
            nodes=[
                {"id": "g", "kind": "gate", "type": "gate.field_changed",
                 "params": {"field": "priority"}},
                _fail_node("chk", "Say more."),
            ],
            edges=[
                {"source": "trg", "port": "out", "target": "g"},
                {"source": "g", "port": "true", "target": "chk"},
            ],
        )


async def test_a_gate_about_the_DRAFT_is_still_allowed_under_a_validate_trigger(
    db, admin, project
):
    """`gate.state_category` asks about the item, not about the event, so it has
    a real answer for a draft. The refusal is scoped to the three that read the
    triggering event — not to gates as a kind, which would take `ai.classify`
    and `ai.validate` with it."""
    rule = await _graph(
        db,
        admin,
        targets=[{"kind": "project", "id": str(project.id)}],
        nodes=[
            {"id": "g", "kind": "gate", "type": "gate.state_category",
             "params": {"category": "todo"}},
            _fail_node("chk", "Say more."),
        ],
        edges=[
            {"source": "trg", "port": "out", "target": "g"},
            {"source": "g", "port": "true", "target": "chk"},
        ],
    )
    assert len(await _bindings(db, rule.id)) == 1


async def test_an_event_gate_on_a_SIBLING_trigger_s_branch_is_untouched(db, admin, project):
    """One graph, two entry points: a validate trigger and an item.created
    trigger. The gate is refused only where it cannot work, which is why the
    check walks what THIS trigger reaches rather than the whole graph."""
    rule = await automations_service.create_rule(
        db,
        RuleCreate(
            name=f"two-entry-points-{uuid.uuid4().hex[:6]}",
            nodes=[
                _validate_trigger([{"kind": "project", "id": str(project.id)}]),
                {"id": "ev", "kind": "trigger", "type": "trigger.event",
                 "params": {"event": "item.created"}},
                {"id": "g", "kind": "gate", "type": "gate.changed_by",
                 "params": {"mode": "any"}},
                _fail_node("chk", "Say more."),
            ],
            edges=[
                {"source": "trg", "port": "out", "target": "chk"},
                {"source": "ev", "port": "out", "target": "g"},
            ],
        ),
        actor_id=admin.id,
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
    assert all(f.mode for f in verdict.findings)  # every finding names its graph


async def test_an_advisory_finding_does_not_block_under_a_co_governing_required_graph(
    db, admin, project
):
    """The bug this test exists for: `mode` is aggregated over EVERY governing
    graph, so "there are findings and the mode is required" refused a draft that
    satisfied the required graph and only tripped the advisory one — while
    `POST /items`, which runs the required bindings alone, accepted the same
    draft. The button and the API disagreed about the same rules.

    The required graph passes here because its check sits behind a filter the
    draft does not match, which is exactly how a conditional check is written.
    """
    await _graph(
        db,
        admin,
        targets=[{"kind": "project", "id": str(project.id)}],
        mode=ValidationMode.REQUIRED.value,
        nodes=[
            {"id": "f", "kind": "filter", "type": "filter.slq",
             "params": {"slq": 'title ~ "outage"'}},
            _fail_node("chk", "An outage report needs a severity."),
        ],
        edges=[
            {"source": "trg", "port": "out", "target": "f"},
            {"source": "f", "port": "matched", "target": "chk"},
        ],
    )
    await _advisory_graph(db, admin, project)
    # The id, not the row: a savepoint rollback EXPIRES what it touched, and
    # reading `project.id` afterwards from a `select(...)` builder is IO outside
    # the greenlet — see `_count_items`.
    project_id = project.id

    outcome = await intake.validate_and_create(
        db, ItemCreate(project_id=project_id, title="a tidy request"), admin
    )
    assert [f.message for f in outcome.verdict.findings] == ["Consider adding a screenshot."]
    # Strictest still, for display: something required IS watching this draft.
    assert outcome.verdict.mode is ValidationMode.REQUIRED
    # …but nothing required OBJECTED, so this is advice, not a refusal.
    assert outcome.verdict.blocks is False

    # THE CLIENT-VISIBLE CONTRACT, which is the half that decides what a person
    # is offered: `blocking` is on the wire because no client can compute it.
    # From `mode` alone this reads as a refusal and the surface hides a "create
    # anyway" the server would have honoured; from `passed` alone it offers one
    # the server refuses. One fact, computed where it is enforced.
    read = verdict_read(outcome.verdict)
    assert read.mode is ValidationMode.REQUIRED
    assert read.blocking is False
    assert read.passed is False

    # And the two paths agree: create-anyway is allowed, and the plain API
    # create — which only ever runs the required bindings — accepts it too.
    kept = await intake.validate_and_create(
        db,
        ItemCreate(project_id=project_id, title="a tidy request"),
        admin,
        commit=intake.IntakeCommit.ALWAYS,
    )
    assert kept.created is not None
    plain = await items_service.create_item(
        db, ItemCreate(project_id=project_id, title="straight in"), actor=admin
    )
    assert plain.title == "straight in"


# --- findings are the VALIDATE trigger's output, and nothing else's -----------


async def test_an_ordinary_walk_collects_no_findings(db, admin, project):
    """A `validation.fail` under a MANUAL trigger records nothing.

    The spec claimed this from the start ("on an ordinary event walk nothing is
    collecting") and the executor did the opposite: it handed every walk the
    report's list, so a check wired into an event graph accumulated findings
    nobody would ever read, and `preview`'s `matched` went true for a graph that
    would apply nothing. Now the walk reads its collecting-ness off the TRIGGER
    it started from.
    """
    rule = await automations_service.create_rule(
        db,
        RuleCreate(
            name=f"manual-with-a-check-{uuid.uuid4().hex[:6]}",
            nodes=[
                {"id": "trg", "kind": "trigger", "type": "trigger.event",
                 "params": {"event": AutomationTrigger.MANUAL.value}},
                _fail_node("chk", "This would be a finding."),
            ],
            edges=[{"source": "trg", "port": "out", "target": "chk"}],
        ),
        actor_id=admin.id,
    )
    draft = await _draft(db, project, admin)
    result = await engine.preview(db, rule, item_id=draft.id)
    assert result.findings == []
    # `matched` is previews-only again: nothing would apply, so a dry run of
    # this graph must not report that something would.
    assert result.matched is False


async def test_a_validate_graph_still_reports_its_findings_on_a_dry_run(db, admin, project):
    """The other half of the same rule. The rule test panel is the only place an
    admin can see what a validation graph would say, so a validate-trigger graph
    collects on every walk — manual, preview, or the intake path."""
    rule = await _graph(
        db,
        admin,
        targets=[{"kind": "project", "id": str(project.id)}],
        nodes=[_fail_node("chk", "A severity is required.")],
        edges=[{"source": "trg", "port": "out", "target": "chk"}],
    )
    draft = await _draft(db, project, admin)
    result = await engine.preview(db, rule, item_id=draft.id)
    assert [f.message for f in result.findings] == ["A severity is required."]


# --- a broken walk is not a failed draft --------------------------------------


async def test_a_walk_that_aborts_the_transaction_is_a_503_not_a_500(
    db, admin, project, monkeypatch
):
    """A DBAPI error inside the walk is SWALLOWED by design — a contributed node
    that raises takes its fallback port so one unreachable provider cannot stop
    a graph with other branches. In Postgres that leaves the transaction
    aborted: every later statement fails, the intake savepoint's RELEASE fails,
    and the person submitting gets a 500 from a create that was fine.

    So the walk runs inside its own savepoint, and a broken one is a clean
    `ValidationUnavailable` with a usable session behind it.
    """
    await _advisory_graph(db, admin, project)
    project_id = project.id
    before = await _count_items(db, project_id)

    async def _poison(session, rule, initial, system_user, **kwargs):
        try:
            await session.execute(text("SELECT 1 / 0"))
        except Exception:
            pass  # exactly what the executor does with a node that raises
        return executor.RunReport()

    monkeypatch.setattr(engine, "run_graph", _poison)
    with pytest.raises(validation.ValidationUnavailable):
        await intake.validate_and_create(
            db, ItemCreate(project_id=project_id, title="a draft"), admin
        )
    # The session survived: this is the query that used to fail with "current
    # transaction is aborted".
    assert await _count_items(db, project_id) == before


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


async def test_a_refused_create_leaves_the_session_clean_for_a_caller_that_carries_on(
    db, admin, project
):
    """The importer's shape: `except Exception`, record a skip, keep going, and
    commit the batch at the end.

    Before this, `create_item` had already flushed the row, its labels and its
    mentions when the hook refused it — only the caller's own rollback took them
    back. A caller that swallowed the error committed a half-created orphan: an
    item with no `item.created` event, invisible to search and to every consumer
    that reads the outbox. The refusal now rolls back to a savepoint taken
    before the insert, so the promise holds whatever the caller does with the
    exception.
    """
    await _required_graph(db, admin, project)
    project_id = project.id
    before = await _count_items(db, project_id)
    try:
        await items_service.create_item(
            db, ItemCreate(project_id=project_id, title="thin"), actor=admin
        )
    except intake.ValidationBlocked:
        pass  # …and carry on, exactly as the Jira importer does
    assert await _count_items(db, project_id) == before
    # The session is usable: the next issue in the batch still imports.
    with events.quiet():
        survivor = await items_service.create_item(
            db, ItemCreate(project_id=project_id, title="the next one"), actor=admin
        )
    assert survivor.title == "the next one"


async def test_the_suppress_scope_is_the_seam_a_machine_channel_uses(db, admin, project):
    """`intake.suppressed()` is public for a reason (spec 119): the mail poller,
    the Alertmanager receiver and the importer all create items, and none of them
    is a person filling in a form. Each wraps its own create in this."""
    await _required_graph(db, admin, project)
    project_id = project.id
    with intake.suppressed():
        created = await items_service.create_item(
            db, ItemCreate(project_id=project_id, title="ALERT: disk full"), actor=admin
        )
    assert created.title == "ALERT: disk full"
    assert intake.is_suppressed() is False  # the scope closed


async def test_a_monitoring_webhook_is_not_asked_for_repro_steps(
    db, admin, project, monkeypatch
):
    """The Alertmanager receiver at its real call site.

    A required check refusing here raises out of the webhook handler, which
    answers Alertmanager with a 5xx it retries forever — and the alert nobody
    can see is the one that matters. The mail poller is the same failure with a
    quieter shape (it marks the message Seen and the request is simply gone),
    and it takes the same seam; there is no cheap fixture for a live IMAP
    round trip, so this is the one that stands for both.
    """
    from radd.modules.alertmanager import service as alertmanager_service

    await _required_graph(db, admin, project)
    project_id = project.id
    monkeypatch.setattr(app_settings, "alertmanager_project_key", project.key)
    counts = await alertmanager_service.process(
        db,
        {
            "alerts": [
                {
                    "fingerprint": uuid.uuid4().hex,
                    "status": "firing",
                    "labels": {"alertname": "DiskFull", "severity": "critical"},
                    "annotations": {"description": "/ is at 98%"},
                }
            ]
        },
    )
    assert counts["created"] == 1
    assert await _count_items(db, project_id) == 1


async def test_disabling_the_plugin_disables_the_enforcement(db, admin, project):
    """`HookRegistry.on()` appends and nothing takes it back, so the handler
    survives the unmount that removes this module's routes and atoms — and went
    on refusing creations from a plugin that was turned off.

    The kernel registry is the fact it now consults, which is the same seam
    `ai.features.plugin_loaded` uses for every sideways call into a disableable
    module. Driven here through the REAL unmount (`registries.unregister_plugin`)
    rather than a flag of the module's own, because a flag would be a second
    copy of the answer.
    """
    from radd.kernel.registry import registries
    from radd.modules.automations import plugin as automations_plugin

    await _required_graph(db, admin, project)
    project_id = project.id
    registries.unregister_plugin(automations_plugin)
    try:
        created = await items_service.create_item(
            db, ItemCreate(project_id=project_id, title="no checks now"), actor=admin
        )
        assert created.title == "no checks now"
    finally:
        registries.register_plugin(automations_plugin)
    with pytest.raises(intake.ValidationBlocked):
        await items_service.create_item(
            db, ItemCreate(project_id=project_id, title="checked again"), actor=admin
        )


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


# --- the form surfaces know what type they will submit (RADD-1060) ------------


async def _form(db, admin, project, *, type_name=None):
    from radd.modules.forms import service as forms_service
    from radd.modules.forms.schemas import FormCreate, FormDefaults

    read = await forms_service.create_form(
        db,
        FormCreate(
            project_id=project.id,
            name=f"Intake {uuid.uuid4().hex[:6]}",
            defaults=FormDefaults(type_name=type_name),
        ),
        actor=admin,
    )
    return read.id


async def test_a_form_resolves_the_type_its_submissions_will_carry(db, admin, project):
    """A form's submitter never picks a type — `submit_form` resolves the form's
    `type_name` default and `create_item` falls back to the project's default —
    so a TYPE-targeted binding was invisible to both form pages: the button said
    "Submit", nothing promised a check, and the rules announced themselves for
    the first time in a 422. The resolution is server-side, on the payload each
    page already fetches.
    """
    from radd.modules.forms import service as forms_service

    bug = await itemtypes_service.create_type(
        db,
        IssueTypeCreate(
            project_id=project.id, name=f"Defect {uuid.uuid4().hex[:6]}", color="#ff0000"
        ),
        actor_id=admin.id,
    )
    form_id = await _form(db, admin, project, type_name=bug.name)
    await _graph(
        db,
        admin,
        targets=[{"kind": "issue_type", "id": str(bug.id)}],
        mode=ValidationMode.REQUIRED.value,
        nodes=[_fail_node("chk", "Bugs need repro steps.", field="description")],
        edges=[{"source": "trg", "port": "out", "target": "chk"}],
    )
    read = await forms_service.render_form(db, form_id, actor=admin)
    assert read.validation is not None
    assert read.validation.governed is True
    assert read.validation.mode == ValidationMode.REQUIRED.value


async def test_a_form_with_no_type_default_falls_back_to_the_projects(db, admin, project):
    """`create_item` falls back to the project's default type, so the form
    surface has to resolve the same way — otherwise the two disagree about what
    is being submitted."""
    from radd.modules.forms import service as forms_service

    default_type = await itemtypes_service.default_type(db, project.id)
    assert default_type is not None  # a project seeds one
    form_id = await _form(db, admin, project)
    await _graph(
        db,
        admin,
        targets=[{"kind": "issue_type", "id": str(default_type.id)}],
        nodes=[_fail_node("chk", "Say more.")],
        edges=[{"source": "trg", "port": "out", "target": "chk"}],
    )
    read = await forms_service.render_form(db, form_id, actor=admin)
    assert read.validation is not None and read.validation.governed is True


# --- the node as the BUILDER sees it (RADD-1064) -------------------------------


async def test_the_catalog_serves_the_checks_own_ports(db, admin):
    """The canvas draws a node's handles before the server has ever seen the
    graph, so what it draws is whatever the catalog told it.

    `ai.validate` is a GATE, and a gate's kind-level ports are true/false — so a
    client with nothing better to go on drew TRUE/FALSE on a node that emits
    pass/fail/unavailable, and every edge dragged off those handles was refused
    by `graph.validate` on save. The fix is that a node with FIXED ports says so,
    and the catalog carries the declaration.

    `ai.classify` proves the other half: its ports are the answers being typed,
    so it declares none and the editor computes them locally. An empty list here
    is a positive statement, not a gap.
    """
    from radd.modules.automations.router import get_catalog

    catalog = await get_catalog(db, admin)
    by_key = {node.key: node for node in catalog.contributed_nodes}

    assert by_key["ai.validate"].ports == ["pass", "fail", "unavailable"]
    assert by_key["ai.classify"].ports == []
    # `default_ports` still answers for the params-dependent node, and is still
    # not a port set: an unconfigured classifier has only its fallback.
    assert by_key["ai.classify"].default_ports == ["unavailable"]


async def test_the_checks_ports_are_wireable_and_a_gates_are_not(db, admin, project):
    """The same fact from the WRITE side, which is where the mis-drawn handle
    turned into a refused save."""
    check = {
        "id": "ai",
        "kind": "gate",
        "type": "ai.validate",
        "params": {"prompt": "A report must say what was expected."},
    }
    targets = [{"kind": "project", "id": str(project.id)}]

    for port in ("pass", "fail", "unavailable"):
        rule = await _graph(
            db,
            admin,
            targets=targets,
            nodes=[check, _fail_node("say", f"took {port}")],
            edges=[
                {"source": "trg", "port": "out", "target": "ai"},
                {"source": "ai", "port": port, "target": "say"},
            ],
        )
        assert rule.id is not None

    with pytest.raises(ConflictError) as refused:
        await _graph(
            db,
            admin,
            targets=targets,
            nodes=[check, _fail_node("say", "took true")],
            edges=[
                {"source": "trg", "port": "out", "target": "ai"},
                # What the canvas drew before RADD-1064.
                {"source": "ai", "port": "true", "target": "say"},
            ],
        )
    assert "no 'true' port" in str(refused.value)


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


async def test_a_spent_budget_reaches_the_ai_node_and_does_not_block_intake(
    db, admin, project, monkeypatch
):
    """The wall-clock budget, end to end (spec 119).

    The walk holds the project's number lock, so a verdict cannot be allowed to
    take as long as the provider feels like taking. `run_graphs` sets one
    deadline for every governing graph, `walk` carries it, and the node asks
    before it spends a round trip — with the budget at zero the provider is
    never called at all, and the draft is created, because an overloaded model
    server must not become a closed intake.
    """
    from radd.modules.ai import automation_node_validate as ai_validate

    async def _never(_ctx, _params):  # pragma: no cover - must not be called
        raise AssertionError("the provider must not be asked after the budget is spent")

    async def _enabled(_session, _feature):  # pragma: no cover - must not be reached
        raise AssertionError("the feature gate should not even be consulted")

    monkeypatch.setattr("radd.modules.ai.features.feature_enabled", _enabled)
    monkeypatch.setattr(ai_validate, "_ask", _never)
    monkeypatch.setattr(app_settings, "intake_validation_budget_seconds", 0.0)

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
        cookie = await auth_service.create_session(session, admin, method=LoginMethod.PASSWORD)
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
    # What the client gates "create anyway" on — the server's own `blocks`,
    # never `mode == required` recomputed at the other end of the wire.
    assert body["verdict"]["blocking"] is True
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
    # The same fact the 200 verdict carries and the 409 is decided by, so a
    # client reads one flag whichever way the answer arrives.
    assert body["blocking"] is True
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
