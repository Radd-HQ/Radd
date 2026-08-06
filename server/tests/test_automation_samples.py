"""Seeing what an event carries, and what each node emitted (RADD-921).

Two questions that had no answer in the product. "What is in an `item.updated`
payload?" — you wrote a dotted path, saved, waited for the event, and learned
from the absence of an effect that you had guessed wrong. "Which items came out
of my filter?" — the dry run reported one boolean and a flat list of actions,
the shape of a linear rule.

The flattening is pure and tested as such. The dry run is tested through the
executor, because what it reports has to be what the walk actually did.
"""

import uuid

import pytest

from radd.modules.automations import executor, samples
from radd.modules.automations.conditions import EventFacts
from radd.modules.automations.graph import Edge, Node, Packet
from radd.modules.automations.types import AutomationNodeKind, NodeArity, NodePort, ARITY_PARAM


# --- payload paths (pure) -----------------------------------------------------


def test_paths_address_list_elements_not_the_list():
    """`changes` is a list of `{field, from, to}`. The addressable path is
    `changes.field`, because that is what `_payload_path` descends to and what
    `{{payload.changes.field}}` renders — `changes` alone addresses nothing
    usable."""
    paths = samples.payload_paths(
        [{"changes": [{"field": "state", "from": "Todo", "to": "Done"}], "item_id": "x"}]
    )
    by_path = {entry.path: entry for entry in paths}

    assert "changes.field" in by_path
    assert "changes" not in by_path
    assert by_path["changes.field"].repeated is True
    assert by_path["item_id"].repeated is False


def test_several_payloads_are_unioned_with_their_values():
    """One event under-describes the shape: an update that changed the state and
    one that changed the assignee produce different `changes` entries, and
    someone writing a condition needs the union."""
    paths = samples.payload_paths(
        [
            {"changes": [{"field": "state", "to": "Done"}]},
            {"changes": [{"field": "assignee", "to": "ada@example.com"}]},
        ]
    )
    by_path = {entry.path: entry for entry in paths}

    assert by_path["changes.field"].examples == ["state", "assignee"]
    assert set(by_path["changes.to"].examples) == {"Done", "ada@example.com"}


def test_examples_are_capped_and_deduplicated():
    payloads = [{"state": "Todo"} for _ in range(20)] + [{"state": f"S{n}"} for n in range(20)]
    entry = next(e for e in samples.payload_paths(payloads) if e.path == "state")
    assert len(entry.examples) <= samples.MAX_EXAMPLES
    assert len(set(entry.examples)) == len(entry.examples)


def test_no_events_yields_no_paths_rather_than_a_guess():
    """A hand-written example shape would be a second copy of what twenty
    modules' `emit` calls define, and would drift silently. Nothing is the
    honest answer, and the UI says so."""
    assert samples.payload_paths([]) == []
    assert samples.changed_fields([]) == []


def test_changed_fields_are_what_the_diff_really_names():
    """The gate's picker otherwise offers every custom-field key, including ones
    the diff never names — a condition that can only ever be false, and looks
    exactly like one that has not matched yet."""
    fields = samples.changed_fields(
        [
            {"changes": [{"field": "state"}, {"field": "cf.severity"}]},
            {"changes": [{"field": "state"}]},
            {"nothing": True},
        ]
    )
    assert fields == ["cf.severity", "state"]


def test_deep_nesting_stops_rather_than_producing_an_unreadable_list():
    deep: dict = {"a": {"b": {"c": {"d": {"e": {"f": "too far"}}}}}}
    paths = [entry.path for entry in samples.payload_paths([deep])]
    assert all(path.count(".") < samples.MAX_DEPTH for path in paths)


# --- what each port emitted ---------------------------------------------------


FACTS = EventFacts(
    event_type="manual", actor_id=None, actor_email=None, actor_name=None, payload={}
)
TRIGGER = Node(id="t", kind=AutomationNodeKind.TRIGGER, type="trigger.event", params={})


class _Item:
    def __init__(self, item_id: uuid.UUID):
        self.id = item_id


@pytest.fixture
def stub_load(monkeypatch):
    async def fake_load(_session, item_ids):
        return [(_Item(i), object()) for i in item_ids]

    async def fake_one(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_load", fake_load)
    monkeypatch.setattr(executor, "_one", fake_one)


async def _walk(nodes, edges, item_ids):
    return await executor.walk(
        None,
        nodes=nodes,
        edges=edges,
        trigger=TRIGGER,
        initial=Packet.of(FACTS, item=tuple(item_ids)),
        system_user=object(),
        automation_name="test",
        budget=executor.new_budget(),
        apply=False,
    )


async def test_the_report_keeps_which_items_left_each_port(stub_load):
    """Counts answer "did my filter narrow anything". They cannot answer "did it
    keep the right ones", which is the question someone debugging has."""
    items = [uuid.UUID(int=n) for n in (1, 2, 3, 4)]
    filter_node = Node(
        id="f", kind=AutomationNodeKind.FILTER, type="filter.slq", params={"slq": ""}
    )
    report = await _walk([TRIGGER, filter_node], [Edge("t", NodePort.OUT.value, "f")], items)

    # An empty query matches everything, so all four leave by `matched`.
    assert report.per_node["f"]["matched"] == 4
    assert report.port_items["f"][NodePort.MATCHED.value] == tuple(items)
    assert report.port_items["f"][NodePort.UNMATCHED.value] == ()
    assert report.incoming_items["f"] == tuple(items)


async def test_the_sample_is_capped_but_the_count_stays_exact(stub_load, monkeypatch):
    """A 200-item run must not build a report bigger than the work it describes —
    and a filter that matched 200 must not REPORT 10 because that is all the
    report kept."""
    monkeypatch.setattr(executor, "SAMPLE_ITEMS", 3)
    items = [uuid.UUID(int=n) for n in range(1, 21)]
    filter_node = Node(
        id="f", kind=AutomationNodeKind.FILTER, type="filter.slq", params={"slq": ""}
    )
    report = await _walk([TRIGGER, filter_node], [Edge("t", NodePort.OUT.value, "f")], items)

    assert report.per_node["f"]["matched"] == 20
    assert len(report.port_items["f"][NodePort.MATCHED.value]) == 3


async def test_an_untaken_gate_branch_is_recorded_as_untaken_not_as_zero(stub_load):
    """The distinction the whole dry run turns on: a port that emitted zero items
    is a filter matching nothing, a port that did not fire is a branch that was
    never taken, and they send someone looking in different places."""
    gate = Node(
        id="g",
        kind=AutomationNodeKind.GATE,
        type="gate.changed_by",
        params={"users": ["nobody"]},
    )
    report = await _walk([TRIGGER, gate], [Edge("t", NodePort.OUT.value, "g")], [uuid.UUID(int=1)])

    # No actor matches, so the gate takes `false` and never emits `true`.
    assert report.not_taken["g"] == [NodePort.TRUE.value]
    assert NodePort.TRUE.value not in report.port_items["g"]
    assert report.per_node["g"][NodePort.FALSE.value] == 1


async def test_a_node_that_never_ran_has_no_entry_at_all(stub_load):
    """Which is how the response tells "did not run" from "ran and found
    nothing" — the detached node reports neither counts nor ports."""
    orphan = Node(id="orphan", kind=AutomationNodeKind.ACTION, type="action.add_label", params={"label": "x"})
    report = await _walk([TRIGGER, orphan], [], [uuid.UUID(int=1)])

    assert "orphan" not in report.per_node
    assert "orphan" not in report.port_items


async def test_a_partitioning_router_reports_each_port_s_own_items(stub_load, monkeypatch):
    """The per-item mode: every port carries the subset that chose it, and the
    empty one is still reported — it is a real answer."""
    from radd.kernel.registry import registries
    from radd.kernel.specs import AutomationNodeSpec

    async def plan_items(ctx):
        return {i: ("odd" if i.int % 2 else "even") for i in ctx.packet.item_ids}

    monkeypatch.setitem(
        registries.automation_nodes,
        "test.split",
        AutomationNodeSpec(
            key="test.split",
            kind="gate",
            label="Split",
            ports_for=lambda _p: ("odd", "even", "none"),
            needs_items=False,
            arity="set",
            arity_options=("set", "item"),
            plan=lambda _ctx: "even",
            plan_items=plan_items,
        ),
    )
    node = Node(
        id="s",
        kind=AutomationNodeKind.GATE,
        type="test.split",
        params={ARITY_PARAM: NodeArity.ITEM.value},
    )
    items = [uuid.UUID(int=n) for n in (1, 2, 3)]
    report = await _walk([TRIGGER, node], [Edge("t", NodePort.OUT.value, "s")], items)

    assert report.port_items["s"]["odd"] == (uuid.UUID(int=1), uuid.UUID(int=3))
    assert report.port_items["s"]["even"] == (uuid.UUID(int=2),)
    assert report.port_items["s"]["none"] == ()
    assert "s" not in report.not_taken  # a partition takes every port
