"""RADD-1329: validation verdicts are visible nodes.

A check only routes and publishes; a "Block submission" node refuses, a "Warn
submitter" node advises. These run the real walk with the AI provider stubbed,
check the leak rule on write, and pin the migration that rewrites stored graphs
so they give the verdict they gave before.
"""

import importlib.util
import uuid
from pathlib import Path

import pytest

from radd.exceptions import ConflictError
from radd.modules.automations import service as automations_service, validation
from radd.modules.automations.schemas import RuleCreate
from radd.modules.automations.types import TYPE_VERDICT_BLOCK, TYPE_VERDICT_WARN
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate

from _factories import make_project


@pytest.fixture
async def project(db):
    return await make_project(db, "VD")


@pytest.fixture
def model(monkeypatch):
    """The AI check with its provider stubbed; set `model.answer` per test."""
    from radd.modules.ai import automation_node_validate as ai_validate

    class Model:
        answer: dict = {"passed": True, "findings": []}

    async def _enabled(_session, _feature):
        return True

    async def _ask(_ctx, _params):
        return Model.answer

    async def _vocabulary(_ctx):
        return {"title", "description"}

    monkeypatch.setattr("radd.modules.ai.features.feature_enabled", _enabled)
    monkeypatch.setattr(ai_validate, "_ask", _ask)
    monkeypatch.setattr(ai_validate, "_field_vocabulary", _vocabulary)
    return Model


def _trigger(project) -> dict:
    return {"id": "trg", "kind": "trigger", "type": "trigger.event",
            "params": {"event": "validate", "targets": [{"kind": "project", "id": str(project.id)}]}}


async def _verdict(db, project, admin, title="a draft"):
    from radd.modules.automations import intake

    with intake.suppressed():  # the draft itself, without the creating hook's refusal
        draft = await items_service.create_item(db, ItemCreate(project_id=project.id, title=title), actor=admin)
    scope = validation.DraftScope(project_id=project.id)
    return await validation.run_graphs(db, draft.id, scope, await validation.governing_graphs(db, scope))


async def _checked_graph(db, admin, project):
    """check → fail → Block (relay) · check → warn → Warn (relay)."""
    return await automations_service.create_rule(db, RuleCreate.model_validate({
        "name": f"checked-{uuid.uuid4().hex[:6]}",
        "nodes": [
            _trigger(project),
            {"id": "ai", "kind": "gate", "type": "ai.validate", "params": {"prompt": "Say what broke."}},
            {"id": "blk", "kind": "action", "type": TYPE_VERDICT_BLOCK, "params": {"relay": "ai"}},
            {"id": "wrn", "kind": "action", "type": TYPE_VERDICT_WARN, "params": {"relay": "ai"}},
        ],
        "edges": [
            {"source": "trg", "port": "out", "target": "ai"},
            {"source": "ai", "port": "fail", "target": "blk"},
            {"source": "ai", "port": "warn", "target": "wrn"},
        ],
    }), admin.id)


async def test_a_blocking_problem_refuses_and_a_minor_one_rides_along_as_advice(db, admin, project, model):
    await _checked_graph(db, admin, project)
    model.answer = {"passed": False, "findings": [
        {"message": "Name the version.", "field": "description", "severity": "blocking"},
        {"message": "A screenshot would help.", "severity": "minor"},
    ]}
    verdict = await _verdict(db, project, admin)
    assert verdict.blocks is True
    assert [(f.message, f.mode) for f in verdict.findings] == [
        ("Name the version.", "required"),
        # Relayed through the BLOCK node, but the model graded it minor.
        ("A screenshot would help.", "advisory"),
    ]
    # A relayed finding names the check that produced it.
    assert {f.node_id for f in verdict.findings} == {"ai"}


async def test_only_minor_problems_warn_and_do_not_refuse(db, admin, project, model):
    await _checked_graph(db, admin, project)
    model.answer = {"passed": False, "findings": [{"message": "A screenshot would help.", "severity": "minor"}]}
    verdict = await _verdict(db, project, admin)
    assert verdict.passed is False and verdict.blocks is False
    assert [f.mode for f in verdict.findings] == ["advisory"]


async def test_a_clean_draft_says_nothing(db, admin, project, model):
    await _checked_graph(db, admin, project)
    model.answer = {"passed": True, "findings": []}
    verdict = await _verdict(db, project, admin)
    assert verdict.passed is True and verdict.findings == ()


async def test_a_message_may_only_use_the_drafts_own_tokens(db, admin, project):
    """Spec 119's leak rule, enforced on write: anything but `{{item.*}}` was read
    with the automation's access, and the message is shown to whoever submitted."""
    def graph(message: str) -> RuleCreate:
        return RuleCreate.model_validate({
            "name": f"leak-{uuid.uuid4().hex[:6]}",
            "nodes": [_trigger(project), {"id": "w", "kind": "action", "type": TYPE_VERDICT_WARN,
                                          "params": {"message": message}}],
            "edges": [{"source": "trg", "port": "out", "target": "w"}],
        })

    with pytest.raises(ConflictError, match="not about the draft"):
        await automations_service.create_rule(db, graph("See {{payload.secret}}."), admin.id)
    await automations_service.create_rule(db, graph("“{{item.title}}” needs a description."), admin.id)
    verdict = await _verdict(db, project, admin, title="Crash on save")
    assert [f.message for f in verdict.findings] == ["“Crash on save” needs a description."]


async def test_a_verdict_is_terminal(db, admin, project):
    with pytest.raises(ConflictError):
        await automations_service.create_rule(db, RuleCreate.model_validate({
            "name": f"chained-{uuid.uuid4().hex[:6]}",
            "nodes": [
                _trigger(project),
                {"id": "a", "kind": "action", "type": TYPE_VERDICT_WARN, "params": {"message": "one"}},
                {"id": "b", "kind": "action", "type": TYPE_VERDICT_WARN, "params": {"message": "two"}},
            ],
            "edges": [{"source": "trg", "port": "out", "target": "a"}, {"source": "a", "port": "out", "target": "b"}],
        }), admin.id)


# --- the migration ----------------------------------------------------------------


def _migration():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "d1329verdict_validation_verdict_nodes.py"
    spec = importlib.util.spec_from_file_location("d1329verdict", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_turns_a_required_ai_check_into_block_and_warn_relays():
    m = _migration()
    nodes = [
        {"id": "trg", "kind": "trigger", "type": "trigger.event",
         "params": {"event": "validate", "targets": [], "mode": "required"}},
        {"id": "ai", "kind": "gate", "type": "ai.validate", "params": {"prompt": "x", "on_unavailable": "fail"}},
    ]
    edges = [{"source": "trg", "port": "out", "target": "ai"}]
    out_nodes, out_edges, can_block = m.rewrite(nodes, edges)
    by_id = {n["id"]: n for n in out_nodes}
    assert "mode" not in by_id["trg"]["params"] and "on_unavailable" not in by_id["ai"]["params"]
    wired = {(e["port"], by_id[e["target"]]["type"], tuple(sorted(by_id[e["target"]]["params"]))) for e in out_edges if e["source"] == "ai"}
    assert wired == {
        ("fail", "verdict.block", ("relay",)),
        ("warn", "verdict.warn", ("relay",)),
        ("unavailable", "verdict.block", ("message",)),
    }
    assert can_block == {"trg": True}


def test_the_migration_turns_report_a_problem_into_a_verdict_and_bypasses_its_chain():
    m = _migration()
    nodes = [
        {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": "validate", "targets": []}},
        {"id": "f", "kind": "filter", "type": "filter.slq", "params": {"slq": "priority = blocker"}},
        {"id": "a", "kind": "action", "type": "validation.fail", "params": {"message": "Assign it.", "field": "assignee"}},
        {"id": "b", "kind": "action", "type": "validation.fail", "params": {"message": "Say why."}},
    ]
    edges = [
        {"source": "trg", "port": "out", "target": "f"},
        {"source": "f", "port": "matched", "target": "a"},
        {"source": "a", "port": "out", "target": "b"},
    ]
    out_nodes, out_edges, can_block = m.rewrite(nodes, edges)
    types = {n["id"]: n["type"] for n in out_nodes}
    # Advisory (no mode) → Warn; the chain a → b is re-sourced from a's feeder.
    assert types["a"] == types["b"] == "verdict.warn"
    assert {(e["source"], e["port"], e["target"]) for e in out_edges} == {
        ("trg", "out", "f"), ("f", "matched", "a"), ("f", "matched", "b"),
    }
    assert can_block == {"trg": False}


def test_the_migration_leaves_an_event_graph_alone_apart_from_the_dead_param():
    m = _migration()
    nodes = [
        {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": "item.created"}},
        {"id": "ai", "kind": "gate", "type": "ai.validate", "params": {"prompt": "x", "on_unavailable": "pass"}},
    ]
    edges = [{"source": "trg", "port": "out", "target": "ai"}]
    out_nodes, out_edges, can_block = m.rewrite(nodes, edges)
    assert [n["id"] for n in out_nodes] == ["trg", "ai"] and out_edges == edges and can_block == {}
    assert "on_unavailable" not in out_nodes[1]["params"]
