"""The `ai.validate` node (spec 119) — the half of intake validation that writes.

The client seam is MOCKED throughout: what is worth pinning is what the node
does with an answer, not that httpx works. Four decisions in particular, each of
which is a way for an AI check to be quietly wrong:

* findings WIN over the model's own `passed` flag, so a model that lists three
  problems and then ticks "fine" cannot throw away the part with information in
  it;
* an unknown field key DEGRADES to a general finding instead of being dropped —
  the advice is still worth reading, it just has no control to attach to;
* an outage takes the `unavailable` port and, by default, blocks NOTHING: a
  provider being down is not evidence that a submission is bad;
* on an ordinary event walk, where nothing is collecting findings, it is a pure
  router — the same node in both graphs with no mode switch.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from radd.modules.ai import automation_node_validate as node
from radd.modules.ai.types import AiFeature


@dataclass
class _Node:
    id: str = "chk"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Packet:
    item_ids: tuple[uuid.UUID, ...] = ()


@dataclass
class _Ctx:
    """Duck-types `automations.executor._NodeContext` — the seam the node is
    written against. Deliberately a stand-in rather than the real class: `ai`
    contributes this node through the KERNEL and must keep working without
    importing anything from `automations`, and a test that imported it would
    stop noticing if that ever changed.

    Its `add_finding` is unconditional, and that is the point: everything about
    WHETHER a finding is collected belongs to the executor, and the tests that
    pin that use the real context (see the two-graph section at the bottom).
    """

    node: _Node = field(default_factory=_Node)
    packet: _Packet = field(default_factory=lambda: _Packet((uuid.uuid4(),)))
    session: Any = None
    actor: Any = None
    collected: list[tuple[str, str]] = field(default_factory=list)
    #: Whether the walk's wall-clock budget is spent (spec 119). A method rather
    #: than a field because that is the shape the node calls it with.
    spent: bool = False

    def out_of_time(self) -> bool:
        return self.spent

    def add_finding(self, message: str, field_key: str = "") -> None:
        self.collected.append((message, field_key))


BAR = {"prompt": "A bug report must name the version and the steps to reproduce."}


@pytest.fixture
def wired(monkeypatch):
    """Feature on, vocabulary fixed, provider stubbed by each test."""

    async def _enabled(_session, feature):
        assert feature is AiFeature.VALIDATION
        return True

    async def _vocabulary(_ctx):
        return {"title", "description", "assignee", "cf.severity"}

    monkeypatch.setattr("radd.modules.ai.features.feature_enabled", _enabled)
    monkeypatch.setattr(node, "_field_vocabulary", _vocabulary)


def _answers(monkeypatch, payload):
    async def _ask(_ctx, _params):
        return payload

    monkeypatch.setattr(node, "_ask", _ask)


# --- ports ---------------------------------------------------------------------


def test_the_ports_are_fixed_and_the_fallback_is_last():
    """`ai.classify`'s ports are a function of its params because its answers ARE
    its branches. Here the answers are prose; what varies is what the model says,
    not how many ways the packet can go. The fallback stays LAST because the
    executor treats a contributed router's final port as its fallback."""
    assert node.SPEC.ports == ("pass", "fail", "unavailable")
    assert node.SPEC.ports_at({"prompt": "x"}) == node.PORTS
    assert node.SPEC.ports_at({})[-1] == node.FALLBACK_PORT


def test_the_ports_are_DECLARED_so_a_client_can_draw_them():
    """RADD-1064: static ports are a declaration, not something inferred from
    `ports_for({})`.

    The distinction is what the canvas reads. Asking a DYNAMIC node for its
    default ports answers about a node nobody has configured yet, so a client
    that treated that as the port set would be wrong for `ai.classify` and had
    no way to be right for this one — it fell back to the KIND's table and drew
    a gate's TRUE/FALSE handles, which the graph validator then refused on save.
    """
    from radd.modules.ai import automation_node as classifier

    assert node.SPEC.ports == node.PORTS  # fixed: declared
    assert classifier.SPEC.ports == ()  # dynamic: deliberately undeclared
    # …and the dynamic one still answers, from its params.
    assert classifier.SPEC.ports_at({"answers": ["bug", "feature"]})[:2] == ("bug", "feature")


# --- the happy paths -----------------------------------------------------------


async def test_a_clean_draft_passes_and_says_nothing(wired, monkeypatch):
    _answers(monkeypatch, {"passed": True, "findings": []})
    ctx = _Ctx(node=_Node(params=dict(BAR)))
    assert await node.plan(ctx) == node.PASS_PORT
    assert ctx.collected == []


async def test_findings_are_recorded_against_their_fields(wired, monkeypatch):
    _answers(
        monkeypatch,
        {
            "passed": False,
            "findings": [
                {"message": "Name the version you saw this on.", "field": "description"},
                {"message": "Pick a severity.", "field": "cf.severity"},
            ],
        },
    )
    ctx = _Ctx(node=_Node(params=dict(BAR)))
    assert await node.plan(ctx) == node.FAIL_PORT
    assert ctx.collected == [
        ("Name the version you saw this on.", "description"),
        ("Pick a severity.", "cf.severity"),
    ]


async def test_findings_beat_the_models_own_passed_flag(wired, monkeypatch):
    """A model that listed problems and then ticked "passed" has told us about
    the problems. Honouring the flag throws away the informative half."""
    _answers(
        monkeypatch,
        {"passed": True, "findings": [{"message": "There are no steps to reproduce."}]},
    )
    ctx = _Ctx(node=_Node(params=dict(BAR)))
    assert await node.plan(ctx) == node.FAIL_PORT
    assert ctx.collected == [("There are no steps to reproduce.", "")]


async def test_an_unknown_field_degrades_to_a_general_finding(wired, monkeypatch):
    """Dropping it would lose real advice; passing it through would send the
    client hunting for a control that does not exist."""
    _answers(
        monkeypatch,
        {"passed": False, "findings": [{"message": "Say which module.", "field": "cf.module"}]},
    )
    ctx = _Ctx(node=_Node(params=dict(BAR)))
    assert await node.plan(ctx) == node.FAIL_PORT
    assert ctx.collected == [("Say which module.", "")]


async def test_blank_and_malformed_findings_are_discarded(wired, monkeypatch):
    """An empty finding refuses a submission while explaining nothing."""
    _answers(
        monkeypatch,
        {
            "passed": False,
            "findings": [
                {"message": "   "},
                "not an object",
                {"field": "title"},
                {"message": "Give it a real title.", "field": "title"},
            ],
        },
    )
    ctx = _Ctx(node=_Node(params=dict(BAR)))
    assert await node.plan(ctx) == node.FAIL_PORT
    assert ctx.collected == [("Give it a real title.", "title")]


async def test_the_finding_count_is_capped(wired, monkeypatch):
    _answers(
        monkeypatch,
        {"passed": False, "findings": [{"message": f"problem {n}"} for n in range(20)]},
    )
    ctx = _Ctx(node=_Node(params={**BAR, "max_findings": 2}))
    assert await node.plan(ctx) == node.FAIL_PORT
    assert [message for message, _ in ctx.collected] == ["problem 0", "problem 1"]


def test_the_cap_is_clamped_to_the_ceiling_whatever_the_param_says():
    assert node.max_findings({"max_findings": 900}) == node.MAX_FINDINGS_CEILING
    assert node.max_findings({"max_findings": 0}) == 1
    assert node.max_findings({"max_findings": "many"}) == node.DEFAULT_MAX_FINDINGS
    assert node.max_findings({}) == node.DEFAULT_MAX_FINDINGS


# --- outage and dormancy -------------------------------------------------------


async def test_a_provider_failure_takes_the_fallback_and_blocks_nothing(wired, monkeypatch):
    """The default. A provider being unreachable is not evidence that a
    submission is bad, and an AI outage that silently refused every intake would
    be the worst possible failure mode for this feature."""

    async def _boom(_ctx, _params):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(node, "_ask", _boom)
    ctx = _Ctx(node=_Node(params=dict(BAR)))
    assert await node.plan(ctx) == node.FALLBACK_PORT
    assert ctx.collected == []


async def test_an_admin_may_choose_to_refuse_when_the_check_cannot_run(wired, monkeypatch):
    """Deliberate and visible: `on_unavailable: fail` turns every outage into a
    refused intake, and says so in the message the submitter reads."""

    async def _boom(_ctx, _params):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(node, "_ask", _boom)
    ctx = _Ctx(node=_Node(params={**BAR, "on_unavailable": "fail"}))
    assert await node.plan(ctx) == node.FALLBACK_PORT
    assert ctx.collected == [(node.UNAVAILABLE_MESSAGE, "")]


async def test_a_dormant_feature_routes_to_the_fallback(monkeypatch):
    """Consistent with `ai.classify`: the toggle off or the chat role
    unconfigured is the same answer as the provider being down."""

    async def _disabled(_session, _feature):
        return False

    monkeypatch.setattr("radd.modules.ai.features.feature_enabled", _disabled)
    ctx = _Ctx(node=_Node(params=dict(BAR)))
    assert await node.plan(ctx) == node.FALLBACK_PORT
    assert ctx.collected == []


async def test_a_node_with_no_bar_is_quiet_rather_than_blocking(monkeypatch):
    """An unfinished node must not refuse every submission — the gate is not
    even consulted, so a half-built graph costs no model round trips either."""

    async def _never(_session, _feature):  # pragma: no cover - must not be called
        raise AssertionError("the feature gate should not be consulted")

    monkeypatch.setattr("radd.modules.ai.features.feature_enabled", _never)
    ctx = _Ctx(node=_Node(params={"prompt": "   "}))
    assert await node.plan(ctx) == node.FALLBACK_PORT
    assert ctx.collected == []


async def test_an_unresolvable_feature_gate_is_an_outage_not_a_crash(monkeypatch):
    """`feature_enabled` RAISES for an unregistered feature by design (RADD-989).
    Letting that escape would take down the whole create, so it is treated as
    the provider being unavailable."""

    async def _explode(_session, _feature):
        raise KeyError("unwired")

    monkeypatch.setattr("radd.modules.ai.features.feature_enabled", _explode)
    ctx = _Ctx(node=_Node(params=dict(BAR)))
    assert await node.plan(ctx) == node.FALLBACK_PORT


# --- the two-graph property ----------------------------------------------------


def _walk_context(*, collecting: bool):
    """A report and the context the EXECUTOR would build for it.

    Through `executor._context`, the factory every call site in `walk` uses —
    not by hand. The version this replaces asserted the two-graph property
    against the stub above, using a `collecting` flag the stub itself invented,
    so it proved that an if-statement in the test file worked. What decides is
    the executor, and at the time it handed a node the report's findings list on
    EVERY walk — the opposite of what the test claimed to show.
    """
    from radd.modules.automations.conditions import EventFacts
    from radd.modules.automations.executor import RunReport, _context
    from radd.modules.automations.graph import Node, Packet
    from radd.modules.automations.types import AutomationNodeKind

    report = RunReport(collecting=collecting)
    ctx = _context(
        report,
        session=None,
        node=Node(
            id="chk", kind=AutomationNodeKind.GATE, type=node.NODE_KEY, params=dict(BAR)
        ),
        packet=Packet.of(
            EventFacts(event_type="validate", actor_id="", actor_email="", actor_name=""),
            item=(uuid.uuid4(),),
        ),
        actor=None,
    )
    return report, ctx


async def test_on_an_ordinary_walk_it_is_a_pure_router(wired, monkeypatch):
    """Nothing is collecting findings outside a validation walk, so `add_finding`
    is a no-op and the node is exactly a pass/fail gate. Same node, both graphs,
    no mode switch."""
    _answers(
        monkeypatch, {"passed": False, "findings": [{"message": "thin", "field": "description"}]}
    )
    report, ctx = _walk_context(collecting=False)
    assert await node.plan(ctx) == node.FAIL_PORT
    assert report.findings == []


async def test_on_a_validation_walk_the_same_call_lands_in_the_collection(wired, monkeypatch):
    """The other half, so neither assertion can pass for the wrong reason: the
    node behaves identically in both, and only what the walk does with the call
    is different."""
    _answers(
        monkeypatch, {"passed": False, "findings": [{"message": "thin", "field": "description"}]}
    )
    report, ctx = _walk_context(collecting=True)
    assert await node.plan(ctx) == node.FAIL_PORT
    assert [(f.message, f.field) for f in report.findings] == [("thin", "description")]


# --- the wall-clock budget -----------------------------------------------------


async def test_a_spent_budget_stops_it_before_the_model_round_trip(wired, monkeypatch):
    """The walk holds the project's number lock while it runs (spec 119), so a
    verdict has a wall clock. Past it this node must not start a request that
    can take another 30 seconds — and it must not silently pass either: the
    check did not run, which is what `unavailable` means."""

    async def _never(_ctx, _params):  # pragma: no cover - must not be called
        raise AssertionError("the provider must not be asked after the budget is spent")

    monkeypatch.setattr(node, "_ask", _never)
    ctx = _Ctx(node=_Node(params=dict(BAR)), spent=True)
    assert await node.plan(ctx) == node.FALLBACK_PORT
    assert ctx.collected == []


async def test_a_spent_budget_still_honours_on_unavailable_fail(wired, monkeypatch):
    """An admin who would rather refuse than accept anything unchecked chose
    that for "the check could not run", and being out of time is exactly that."""

    async def _never(_ctx, _params):  # pragma: no cover - must not be called
        raise AssertionError("the provider must not be asked after the budget is spent")

    monkeypatch.setattr(node, "_ask", _never)
    ctx = _Ctx(node=_Node(params={**BAR, "on_unavailable": "fail"}), spent=True)
    assert await node.plan(ctx) == node.FALLBACK_PORT
    assert ctx.collected == [(node.UNAVAILABLE_MESSAGE, "")]


async def test_a_context_with_no_budget_at_all_is_not_out_of_time(wired, monkeypatch):
    """The node reads the budget off the context by duck typing, so a host that
    never had one — an older executor, a plugin runner — has all the time in the
    world rather than crashing or refusing everything."""

    class _NoBudget:
        node = _Node(params=dict(BAR))
        packet = _Packet((uuid.uuid4(),))
        session = None
        actor = None

        def add_finding(self, message, field_key=""):  # pragma: no cover - unused
            pass

    _answers(monkeypatch, {"passed": True, "findings": []})
    assert await node.plan(_NoBudget()) == node.PASS_PORT


# --- registration --------------------------------------------------------------


def test_the_spec_is_contributed_with_the_shape_the_executor_expects():
    assert node.SPEC.key == "ai.validate"
    assert node.SPEC.kind == "gate"
    assert node.SPEC.plan is plan_of(node)
    # SET-fixed: a validation walk carries exactly one draft, and offering the
    # item reading would invite dropping this into a scheduled run over a broad
    # query — one model round trip per item, with nobody reading the results.
    assert node.SPEC.arity == "set"
    assert node.SPEC.arity_options == ()
    assert node.SPEC.needs_items is True


def plan_of(module):
    return module.plan


def test_the_ai_plugin_registers_its_automation_nodes():
    """Three since spec 120, and they stay three separate nodes on purpose: one
    ROUTES on an enumerated answer, one WRITES PROSE at a person, one FILLS IN
    named values the rest of the graph reads."""
    from radd.modules.ai import plugin as ai_plugin

    assert {spec.key for spec in ai_plugin.automation_nodes} == {
        "ai.classify",
        "ai.validate",
        "ai.generate",
    }
