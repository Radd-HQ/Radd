"""Workflow transitions (specs 61/107): pure guard evaluation + the enforcement seam.

Pure cases run without a DB (guards.py mirrors forms/validation.py). Integration
cases are DB-backed (compose Postgres) — flushed, never committed; the session
rolls back at teardown, so rows never persist.

Spec 107: every data check is one require_field condition ({kind, key, op,
values}) over builtins + custom fields; require_approval carries per-entry
approver rules.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope
from radd.modules.timelogging import service as timelog
from radd.modules.timelogging.schemas import EstimateSet
from radd.modules.workflow import service as workflow, transitions
from radd.modules.workflow.guards import ItemSnapshot, TransitionError, evaluate, is_empty
from radd.modules.workflow.schemas import TransitionCreate, TransitionRule
from radd.modules.workflow.types import TransitionCheck, TransitionMode
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

MODE_KEY = SettingKey.WORKFLOW_TRANSITION_MODE


def field_rule(key: str, op: str = "set", *, kind: str = "builtin", **extra) -> dict:
    return {"check": "require_field", "params": {"kind": kind, "key": key, "op": op, **extra}}


def field_params(key: str, op: str = "set", *, kind: str = "builtin", **extra) -> dict:
    return {"kind": kind, "key": key, "op": op, **extra}


# --- pure guard evaluation ---


def test_presence_conditions_keep_the_legacy_strings():
    rules = [
        field_rule("assignee"),
        field_rule("estimate"),
        field_rule("team"),
        field_rule("comment"),
    ]
    assert evaluate(rules, ItemSnapshot()) == [
        "an assignee is required",
        "an estimate is required",
        "a team is required",
        "at least one comment is required",
    ]
    satisfied = ItemSnapshot(
        builtin={"assignee": "u1", "estimate": True, "team": "t1", "comment": 2}
    )
    assert evaluate(rules, satisfied) == []


def test_resolved_threads_guard_composes_with_existing_conditions():
    rules = [field_rule("assignee"), {"check": "require_resolved_threads", "params": {}}]
    assert evaluate(rules, ItemSnapshot(builtin={"assignee": "u"})) == []
    assert evaluate(rules, ItemSnapshot(has_unresolved_threads=True)) == [
        "an assignee is required", "all threads must be resolved (including internal threads)"
    ]


def test_custom_set_uses_display_labels_and_blank_counts_as_missing():
    rules = [
        field_rule("severity", kind="custom"),
        field_rule("area", kind="custom"),
    ]
    snapshot = ItemSnapshot(
        custom_fields={"severity": "", "area": "backend"},
        field_labels={"severity": "Severity"},
    )
    # severity is blank -> fails with its display label; area is set -> passes.
    assert evaluate(rules, snapshot) == ['"Severity" must be set']
    # Unlabelled keys fall back to the raw key.
    assert evaluate([field_rule("severity", kind="custom")], ItemSnapshot()) == [
        '"severity" must be set'
    ]


def test_is_and_is_not_on_builtin_enums():
    high = [field_rule("priority", "is", values=["high", "blocker"])]
    assert evaluate(high, ItemSnapshot(builtin={"priority": "low"})) == [
        '"Priority" must be one of high, blocker'
    ]
    assert evaluate(high, ItemSnapshot(builtin={"priority": "high"})) == []
    not_low = [field_rule("priority", "is_not", values=["low"])]
    assert evaluate(not_low, ItemSnapshot(builtin={"priority": "low"})) == [
        '"Priority" must not be low'
    ]
    assert evaluate(not_low, ItemSnapshot(builtin={"priority": "high"})) == []


def test_is_not_passes_on_an_empty_value():
    # Nothing isn't the value — is_not only fails on an actual match.
    rules = [field_rule("cycle", "is_not", values=["c1"])]
    assert evaluate(rules, ItemSnapshot(builtin={"cycle": None})) == []


def test_multi_valued_overlap_and_display_names():
    rules = [
        field_rule("labels", "is", values=["l1", "l2"], display=["Bug", "Regression"])
    ]
    assert evaluate(rules, ItemSnapshot(builtin={"labels": ["l3"]})) == [
        '"Labels" must be one of Bug, Regression'
    ]
    assert evaluate(rules, ItemSnapshot(builtin={"labels": ["l2", "l9"]})) == []


def test_date_bounds_phrase_as_dates():
    rules = [field_rule("target_date", "gte", values=["2026-08-01"])]
    late = ItemSnapshot(builtin={"target_date": "2026-07-01"})
    assert evaluate(rules, late) == ['"Target date" must be on or after 2026-08-01']
    assert evaluate(rules, ItemSnapshot(builtin={"target_date": "2026-08-02"})) == []
    # An absent value can't satisfy a bound.
    assert evaluate(rules, ItemSnapshot()) == [
        '"Target date" must be on or after 2026-08-01'
    ]


def test_numeric_custom_bounds_compare_numerically():
    rules = [field_rule("points", "gte", kind="custom", type="number", values=["10"])]
    assert evaluate(rules, ItemSnapshot(custom_fields={"points": 9})) == [
        '"points" must be at least 10'
    ]
    assert evaluate(rules, ItemSnapshot(custom_fields={"points": 10.5})) == []
    equals = [field_rule("points", "is", kind="custom", type="number", values=["5"])]
    assert evaluate(equals, ItemSnapshot(custom_fields={"points": 5.0})) == []


def test_boolean_custom_is():
    rules = [field_rule("signed_off", "is", kind="custom", type="boolean", values=["true"])]
    assert evaluate(rules, ItemSnapshot(custom_fields={"signed_off": False})) == [
        '"signed_off" must be true'
    ]
    assert evaluate(rules, ItemSnapshot(custom_fields={"signed_off": True})) == []


def test_is_empty_accepts_falsey_present_values():
    assert is_empty(None) and is_empty("") and is_empty([])
    assert not is_empty(0) and not is_empty(False)


def test_unknown_checks_and_malformed_conditions_are_skipped():
    assert evaluate([{"check": "require_blessing", "params": {}}], ItemSnapshot()) == []
    assert evaluate([{"check": "require_field", "params": {"op": "wat"}}], ItemSnapshot()) == []


def test_approval_failure_names_the_entries():
    rules = [
        {
            "check": TransitionCheck.REQUIRE_APPROVAL.value,
            "params": {
                "approvers": [
                    {"kind": "user", "id": "u1", "name": "Hussein Jarrar"},
                    {"kind": "team", "id": "t1", "name": "DevOps", "required": 2},
                ]
            },
        }
    ]
    assert evaluate(rules, ItemSnapshot(), to_state_id="s1") == [
        "approval required (Hussein Jarrar; 2 of DevOps)"
    ]
    approved = ItemSnapshot(approved_to_state_ids=frozenset({"s1"}))
    assert evaluate(rules, approved, to_state_id="s1") == []


def test_approval_failure_sorts_last():
    rules = [
        {
            "check": TransitionCheck.REQUIRE_APPROVAL.value,
            "params": {"approvers": [{"kind": "user", "id": "u1", "name": "A"}]},
        },
        field_rule("assignee"),
    ]
    failures = evaluate(rules, ItemSnapshot(), to_state_id="s1")
    assert failures == ["an assignee is required", "approval required (A)"]


def test_transition_error_carries_the_edge():
    err = TransitionError(["an assignee is required"], "Triage", "In Progress")
    assert err.errors == ["an assignee is required"]
    assert err.from_state == "Triage" and err.to_state == "In Progress"
    assert "assignee" in str(err)


# --- integration (DB-backed) ---


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def actor(db) -> User:
    user = User(
        email=f"wt-{uuid.uuid4().hex[:8]}@example.com",
        name="Transition Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _project_with_states(db):
    project = await projects_service.create_project(
        db,
        ProjectCreate(key=f"WT{uuid.uuid4().hex[:4].upper()}", name="P"),
    )
    states = {s.name: s for s in await workflow.list_states(db, project.id)}
    return project, states  # seeded defaults: Triage default, Done, …


async def _set_mode(db, project, mode: TransitionMode) -> None:
    await settings_service.set_value(
        db, MODE_KEY, SettingScope.PROJECT, project.id, mode.value
    )


def _require(key: str, op: str = "set", *, kind: str = "builtin", **extra) -> TransitionRule:
    return TransitionRule(
        check=TransitionCheck.REQUIRE_FIELD, params=field_params(key, op, kind=kind, **extra)
    )


async def _expect_blocked(db, item_id, data, actor) -> TransitionError:
    """Run an update that must raise TransitionError inside a SAVEPOINT and roll
    it back — over HTTP the request's transaction rolls back the same way (and
    the automations engine wraps each action in a savepoint)."""
    savepoint = await db.begin_nested()
    with pytest.raises(TransitionError) as exc:
        await items.update_item(db, item_id, data, actor)
    await savepoint.rollback()
    return exc.value


async def test_mode_off_is_a_no_op(db, actor):
    project, states = await _project_with_states(db)
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            to_state_id=states["In Progress"].id,
            rules=[_require("assignee")],
        ),
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), actor)
    read = await items.update_item(
        db, item.id, ItemUpdate(state_id=states["In Progress"].id), actor
    )
    assert read.state.name == "In Progress"  # default mode = off, nothing enforced


async def test_guards_block_until_satisfied(db, actor):
    project, states = await _project_with_states(db)
    await _set_mode(db, project, TransitionMode.GUARDS)
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            from_state_id=states["Triage"].id,
            to_state_id=states["In Progress"].id,
            rules=[_require("assignee"), _require("estimate")],
        ),
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), actor)
    error = await _expect_blocked(
        db, item.id, ItemUpdate(state_id=states["In Progress"].id), actor
    )
    assert error.errors == ["an assignee is required", "an estimate is required"]
    assert error.from_state == "Triage" and error.to_state == "In Progress"

    # An unmatched move stays allowed in guards mode (no full graph required).
    await items.update_item(db, item.id, ItemUpdate(state_id=states["Backlog"].id), actor)
    await items.update_item(db, item.id, ItemUpdate(state_id=states["Triage"].id), actor)

    # Satisfy the guards: estimate via the timelogging seam, assignee in the SAME
    # PATCH as the state change (order matters — patched values count).
    await timelog.set_estimate(db, item.id, EstimateSet(estimate="4h"), actor_id=actor.id)
    read = await items.update_item(
        db,
        item.id,
        ItemUpdate(state_id=states["In Progress"].id, assignee_id=actor.id),
        actor,
    )
    assert read.state.name == "In Progress"


async def test_value_condition_blocks_and_passes(db, actor):
    project, states = await _project_with_states(db)
    await _set_mode(db, project, TransitionMode.GUARDS)
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            from_state_id=states["Triage"].id,
            to_state_id=states["Done"].id,
            rules=[_require("priority", "is", values=["high", "blocker"])],
        ),
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), actor)
    error = await _expect_blocked(db, item.id, ItemUpdate(state_id=states["Done"].id), actor)
    assert error.errors == ['"Priority" must be one of high, blocker']
    # The value lands in the SAME PATCH as the state change and counts.
    read = await items.update_item(
        db, item.id, ItemUpdate(state_id=states["Done"].id, priority="high"), actor
    )
    assert read.state.name == "Done"


async def test_wildcard_from_null_applies_from_every_state(db, actor):
    project, states = await _project_with_states(db)
    await _set_mode(db, project, TransitionMode.GUARDS)
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            to_state_id=states["Done"].id,  # from omitted = any source state
            rules=[_require("assignee")],
        ),
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), actor)
    # Triage -> Done blocked by the wildcard row…
    await _expect_blocked(db, item.id, ItemUpdate(state_id=states["Done"].id), actor)
    await items.update_item(db, item.id, ItemUpdate(state_id=states["Backlog"].id), actor)
    # …and Backlog -> Done hits the same row (applies from every source state).
    await _expect_blocked(db, item.id, ItemUpdate(state_id=states["Done"].id), actor)


async def test_strict_blocks_undefined_pairs_only_when_rows_exist(db, actor):
    project, states = await _project_with_states(db)
    await _set_mode(db, project, TransitionMode.STRICT)
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            from_state_id=states["Triage"].id,
            to_state_id=states["In Progress"].id,
        ),
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), actor)
    # Triage -> Done is not a defined pair.
    error = await _expect_blocked(db, item.id, ItemUpdate(state_id=states["Done"].id), actor)
    assert "no transition" in error.errors[0]
    # The defined pair still moves.
    await items.update_item(db, item.id, ItemUpdate(state_id=states["In Progress"].id), actor)

    # A rowless project in strict mode behaves like guards (nothing blocked).
    rowless = await projects_service.create_project(
        db,
        ProjectCreate(key=f"WR{uuid.uuid4().hex[:4].upper()}", name="R"),
    )
    rowless_states = {s.name: s for s in await workflow.list_states(db, rowless.id)}
    other = await items.create_item(db, ItemCreate(project_id=rowless.id, title="j"), actor)
    await items.update_item(db, other.id, ItemUpdate(state_id=rowless_states["Done"].id), actor)


async def test_write_validation_rejects_bad_conditions(db, actor):
    project, states = await _project_with_states(db)
    cases = [
        _require("nope", kind="custom"),  # unknown custom key
        _require("blessing"),  # unknown builtin
        _require("estimate", "is", values=["4h"]),  # op not allowed for the field
        _require("priority", "is", values=["urgent"]),  # unknown priority value
        _require("priority", "is"),  # missing values
        _require("target_date", "gte", values=["soon"]),  # not a date
    ]
    for bad in cases:
        with pytest.raises(ConflictError):
            await transitions.create_transition(
                db,
                TransitionCreate(
                    project_id=project.id, to_state_id=states["Done"].id, rules=[bad]
                ),
            )


async def test_approval_rule_validation_and_name_snapshot(db, actor):
    project, states = await _project_with_states(db)
    # Unknown team id -> 409.
    with pytest.raises(ConflictError):
        await transitions.create_transition(
            db,
            TransitionCreate(
                project_id=project.id,
                to_state_id=states["Done"].id,
                rules=[
                    TransitionRule(
                        check=TransitionCheck.REQUIRE_APPROVAL,
                        params={
                            "approvers": [
                                {"kind": "team", "id": str(uuid.uuid4()), "required": 2}
                            ]
                        },
                    )
                ],
            ),
        )
    # A valid user entry gets its display name snapshotted server-side.
    created = await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            to_state_id=states["Done"].id,
            rules=[
                TransitionRule(
                    check=TransitionCheck.REQUIRE_APPROVAL,
                    params={"approvers": [{"kind": "user", "id": str(actor.id), "name": "spoofed"}]},
                )
            ],
        ),
    )
    entry = created.rules[0]["params"]["approvers"][0]
    assert entry["name"] == actor.name  # never trusted from the client


async def test_write_validation_rejects_self_edges_but_allows_duplicates(db, actor):
    project, states = await _project_with_states(db)
    with pytest.raises(ConflictError):  # from == to
        await transitions.create_transition(
            db,
            TransitionCreate(
                project_id=project.id,
                from_state_id=states["Done"].id,
                to_state_id=states["Done"].id,
            ),
        )
    # Multiple rows per (from, to) are legitimate since applies_when scoping
    # (spec 107 follow-up) — first-match resolves them.
    await transitions.create_transition(
        db, TransitionCreate(project_id=project.id, to_state_id=states["Done"].id)
    )
    await transitions.create_transition(
        db, TransitionCreate(project_id=project.id, to_state_id=states["Done"].id)
    )


# --- applies_when scoping (spec 107 follow-up) ---


def _blocker_only() -> list[dict]:
    return [{"kind": "builtin", "key": "priority", "op": "is", "values": ["blocker"]}]


async def test_applies_when_scopes_the_row_to_matching_items(db, actor):
    project, states = await _project_with_states(db)
    await _set_mode(db, project, TransitionMode.GUARDS)
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            from_state_id=states["Triage"].id,
            to_state_id=states["Done"].id,
            applies_when=_blocker_only(),
            rules=[_require("assignee")],
        ),
    )
    normal = await items.create_item(db, ItemCreate(project_id=project.id, title="n"), actor)
    blocker = await items.create_item(
        db, ItemCreate(project_id=project.id, title="b", priority="blocker"), actor
    )
    # The row doesn't apply to a normal-priority item — guards mode frees it.
    await items.update_item(db, normal.id, ItemUpdate(state_id=states["Done"].id), actor)
    # The blocker item is governed and blocked until the condition holds.
    error = await _expect_blocked(
        db, blocker.id, ItemUpdate(state_id=states["Done"].id), actor
    )
    assert error.errors == ["an assignee is required"]


async def test_applies_when_first_match_expresses_exemptions(db, actor):
    project, states = await _project_with_states(db)
    await _set_mode(db, project, TransitionMode.GUARDS)
    # Row 1: blockers are EXEMPT (no rules); Row 2: everyone else needs an assignee.
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            from_state_id=states["Triage"].id,
            to_state_id=states["Done"].id,
            applies_when=_blocker_only(),
        ),
    )
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            from_state_id=states["Triage"].id,
            to_state_id=states["Done"].id,
            rules=[_require("assignee")],
        ),
    )
    blocker = await items.create_item(
        db, ItemCreate(project_id=project.id, title="b", priority="blocker"), actor
    )
    normal = await items.create_item(db, ItemCreate(project_id=project.id, title="n"), actor)
    # First match: the blocker hits the empty-rules row and moves freely…
    await items.update_item(db, blocker.id, ItemUpdate(state_id=states["Done"].id), actor)
    # …while everyone else falls through to the general row.
    error = await _expect_blocked(
        db, normal.id, ItemUpdate(state_id=states["Done"].id), actor
    )
    assert error.errors == ["an assignee is required"]


async def test_strict_blocks_items_no_row_applies_to(db, actor):
    project, states = await _project_with_states(db)
    await _set_mode(db, project, TransitionMode.STRICT)
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            from_state_id=states["Triage"].id,
            to_state_id=states["Done"].id,
            applies_when=_blocker_only(),
        ),
    )
    normal = await items.create_item(db, ItemCreate(project_id=project.id, title="n"), actor)
    blocker = await items.create_item(
        db, ItemCreate(project_id=project.id, title="b", priority="blocker"), actor
    )
    # The edge is defined, but not for THIS item — strict blocks it outright.
    error = await _expect_blocked(
        db, normal.id, ItemUpdate(state_id=states["Done"].id), actor
    )
    assert "applies to this item" in error.errors[0]
    await items.update_item(db, blocker.id, ItemUpdate(state_id=states["Done"].id), actor)


async def test_applies_when_write_validation(db, actor):
    project, states = await _project_with_states(db)
    with pytest.raises(ConflictError):  # unknown custom key in the scoping clause
        await transitions.create_transition(
            db,
            TransitionCreate(
                project_id=project.id,
                to_state_id=states["Done"].id,
                applies_when=[{"kind": "custom", "key": "nope", "op": "set"}],
            ),
        )


async def test_allowed_transitions_reports_targets(db, actor):
    project, states = await _project_with_states(db)
    await _set_mode(db, project, TransitionMode.GUARDS)
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            from_state_id=states["Triage"].id,
            to_state_id=states["In Progress"].id,
            rules=[_require("assignee")],
        ),
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), actor)
    result = await transitions.allowed_transitions(db, project, await items.require_item(db, item.id))
    assert result.mode is TransitionMode.GUARDS
    by_state = {t.state_id: t for t in result.targets}
    blocked = by_state[states["In Progress"].id]
    assert not blocked.allowed and blocked.failures == ["an assignee is required"]
    assert by_state[states["Done"].id].allowed  # unmatched target stays open in guards


async def test_resolvable_threads_gate_selected_states_and_preserve_regular_replies(db, actor):
    from radd.modules.comments import service as comments, threads
    from radd.modules.comments.schemas import CommentCreate, CommentReplyCreate
    from radd.modules.comments.types import CommentVisibility

    project, states = await _project_with_states(db)
    await _set_mode(db, project, TransitionMode.GUARDS)
    for target in ("Code Review", "Done"):
        await transitions.create_transition(db, TransitionCreate(
            project_id=project.id, to_state_id=states[target].id,
            rules=[TransitionRule(check=TransitionCheck.REQUIRE_RESOLVED_THREADS)],
        ))
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Review discussion"), actor)
    ordinary = await comments.create_comment(db, item.id, CommentCreate(body="FYI"), actor)
    await threads.create_reply(db, ordinary.id, CommentReplyCreate(body="Thanks"), actor)
    assert not ordinary.is_thread
    assert not await comments.has_unresolved_threads(db, item.id)
    with pytest.raises(ConflictError, match="resolvable thread"):
        await comments.set_resolved(db, ordinary.id, actor, resolved=True)
    await items.update_item(db, item.id, ItemUpdate(state_id=states["Code Review"].id), actor)
    root = await comments.create_comment(db, item.id, CommentCreate(
        body="Please address this", is_thread=True, visibility=CommentVisibility.INTERNAL), actor)
    assert root.is_thread and root.resolved_at is None
    assert await comments.has_unresolved_threads(db, item.id)
    allowed = await transitions.allowed_transitions(db, project, await items.require_item(db, item.id))
    done = next(t for t in allowed.targets if t.state_id == states["Done"].id)
    assert not done.allowed and "all threads" in done.failures[0]
    error = await _expect_blocked(db, item.id, ItemUpdate(state_id=states["Done"].id), actor)
    assert "all threads" in error.errors[0]
    await db.refresh(actor)
    # An unprotected target remains reachable, and the second protected target fails too.
    await items.update_item(db, item.id, ItemUpdate(state_id=states["In Progress"].id), actor)
    await _expect_blocked(db, item.id, ItemUpdate(state_id=states["Code Review"].id), actor)
    await db.refresh(actor)
    reply = await threads.create_reply(db, root.id, CommentReplyCreate(body="Fixed"), actor)
    assert not reply.is_thread
    resolved = await comments.set_resolved(db, root.id, actor, resolved=True)
    again = await comments.set_resolved(db, root.id, actor, resolved=True)
    assert (again.resolved_at, again.resolved_by) == (resolved.resolved_at, resolved.resolved_by)
    assert not await comments.has_unresolved_threads(db, item.id)
    assert len((await threads.reply_page(db, root.id, actor)).comments) == 1
    assert not (await comments.comment_page(db, item.id, actor, unresolved=True)).comments
    await items.update_item(db, item.id, ItemUpdate(state_id=states["Code Review"].id), actor)
    await comments.set_resolved(db, root.id, actor, resolved=False)
    feed = await comments.comment_page(db, item.id, actor, unresolved=True)
    assert [c.id for c in feed.comments] == [root.id]
    await _expect_blocked(db, item.id, ItemUpdate(state_id=states["Done"].id), actor)
    await db.refresh(actor)
    await _set_mode(db, project, TransitionMode.OFF)
    await items.update_item(db, item.id, ItemUpdate(state_id=states["Done"].id), actor)


async def test_threads_gate_is_project_and_issue_type_scoped(db, actor):
    from radd.modules.comments import service as comments
    from radd.modules.comments.schemas import CommentCreate
    from radd.modules.itemtypes import service as itemtypes

    project, states = await _project_with_states(db)
    types = await itemtypes.list_types(db, project.id)
    selected = types[0]
    await _set_mode(db, project, TransitionMode.GUARDS)
    await transitions.create_transition(db, TransitionCreate(
        project_id=project.id, to_state_id=states["Done"].id,
        applies_when=[field_params("type", "is", values=[str(selected.id)])],
        rules=[TransitionRule(check=TransitionCheck.REQUIRE_RESOLVED_THREADS)],
    ))
    for type_id, blocked in ((selected.id, True), (types[1].id, False)):
        item = await items.create_item(db, ItemCreate(project_id=project.id, title="Scoped", type_id=type_id), actor)
        await comments.create_comment(db, item.id, CommentCreate(body="Open", is_thread=True), actor)
        if blocked:
            await _expect_blocked(db, item.id, ItemUpdate(state_id=states["Done"].id), actor)
            await db.refresh(actor)
        else:
            await items.update_item(db, item.id, ItemUpdate(state_id=states["Done"].id), actor)
    other, other_states = await _project_with_states(db)
    await _set_mode(db, other, TransitionMode.GUARDS)
    item = await items.create_item(db, ItemCreate(project_id=other.id, title="Other project"), actor)
    await comments.create_comment(db, item.id, CommentCreate(body="Open", is_thread=True), actor)
    await items.update_item(db, item.id, ItemUpdate(state_id=other_states["Done"].id), actor)
