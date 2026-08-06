"""Spec 116: the automation graph's structure rules.

Pure/in-memory — `graph.py` takes no session, so these run without a database and
assert the things the engine is allowed to assume: any number of triggers (a
graph may fire from several entry points, or from none while it is being built),
edges that name ports their source actually emits, no cycles, deterministic
order, and fan-in that unions without duplicating.
"""

import uuid

import pytest

from radd.modules.automations import graph
from radd.modules.automations.graph import Edge, GraphError, Node, Packet
from radd.modules.automations.types import (
    MAX_GRAPH_NODES,
    MAX_GRAPH_TRIGGERS,
    AutomationNodeKind,
    NodePort,
)


def _node(node_id: str, kind: AutomationNodeKind, type_: str = "x") -> Node:
    return Node(id=node_id, kind=kind, type=type_)


TRIGGER = _node("t", AutomationNodeKind.TRIGGER, "trigger.event")
FILTER = _node("f", AutomationNodeKind.FILTER, "filter.slq")
GATE = _node("g", AutomationNodeKind.GATE, "gate.event")
ACTION = _node("a", AutomationNodeKind.ACTION, "action.add_label")


# --- validation --------------------------------------------------------------


def test_linear_graph_validates_and_returns_its_triggers():
    nodes = [TRIGGER, FILTER, ACTION]
    edges = [
        Edge("t", NodePort.OUT, "f"),
        Edge("f", NodePort.MATCHED, "a"),
    ]
    assert graph.validate(nodes, edges) == [TRIGGER]


@pytest.mark.parametrize("count", [0, 1, 2, 5])
def test_a_graph_may_hold_any_number_of_triggers(count):
    """Several is the point: "on create, OR every Monday" is one automation with
    one set of actions, not two graphs kept in step by hand. A firing event starts
    the run at the trigger that matched.

    Zero is legal too — a graph being built is saved before it is wired, and the
    editor says it can never run rather than the API refusing to store work."""
    triggers = [_node(f"t{i}", AutomationNodeKind.TRIGGER) for i in range(count)]
    assert graph.validate([*triggers, ACTION], []) == triggers


def test_too_many_triggers_is_refused():
    """A cap, so one graph cannot subscribe to the whole event catalog by
    accident — every trigger multiplies the runs a single event causes."""
    many = [_node(f"t{i}", AutomationNodeKind.TRIGGER) for i in range(MAX_GRAPH_TRIGGERS + 1)]
    with pytest.raises(GraphError, match="at most"):
        graph.validate(many, [])


def test_a_node_type_may_name_its_own_ports():
    """Spec 116 phase 2: ports come from the node TYPE, not only its kind — and
    they may depend on its params. An AI classifier with four user-defined
    answers has four outputs, which no per-kind table can express, and the
    validator has to know the real set or it cannot reject a bad edge."""
    classifier = Node(
        id="ai",
        kind=AutomationNodeKind.GATE,
        type="ai.classify",
        params={"answers": ["bug", "feature", "question"]},
    )
    action = _node("a", AutomationNodeKind.ACTION)

    def ports_of(node: Node) -> tuple[str, ...]:
        if node.type == "ai.classify":
            return tuple(str(a) for a in node.params.get("answers", ()))
        return graph.default_ports(node)

    nodes = [TRIGGER, classifier, action]
    edges = [
        Edge("t", NodePort.OUT, "ai"),
        # "question" is one of the configured answers, so this is legal even
        # though no NodePort member is named that.
        Edge("ai", NodePort("false"), "a"),
    ]
    # The kind's own ports (true/false) are NOT what this type emits.
    with pytest.raises(GraphError, match="it emits bug, feature, question"):
        graph.validate(nodes, edges, ports_of)


def test_edge_naming_a_port_its_source_cannot_emit_is_rejected():
    """A gate has true/false, not matched/unmatched. Catching this on write is
    the difference between a validation message and a branch that silently never
    runs."""
    nodes = [TRIGGER, GATE, ACTION]
    edges = [Edge("t", NodePort.OUT, "g"), Edge("g", NodePort.MATCHED, "a")]
    with pytest.raises(GraphError, match="no 'matched' port"):
        graph.validate(nodes, edges)


def test_filter_emits_both_of_its_ports():
    """The per-item if/else: one filter, two actions, opposite ports. This is the
    shape that made a separate Filter kind worth having."""
    other = _node("a2", AutomationNodeKind.ACTION)
    nodes = [TRIGGER, FILTER, ACTION, other]
    edges = [
        Edge("t", NodePort.OUT, "f"),
        Edge("f", NodePort.MATCHED, "a"),
        Edge("f", NodePort.UNMATCHED, "a2"),
    ]
    assert graph.validate(nodes, edges) == [TRIGGER]


def test_cycles_are_rejected_with_the_offending_nodes_named():
    a, b = _node("a", AutomationNodeKind.ACTION), _node("b", AutomationNodeKind.ACTION)
    nodes = [TRIGGER, a, b]
    edges = [
        Edge("t", NodePort.OUT, "a"),
        Edge("a", NodePort.OUT, "b"),
        Edge("b", NodePort.OUT, "a"),  # back edge
    ]
    with pytest.raises(GraphError, match="cycle: a, b"):
        graph.validate(nodes, edges)


def test_edges_to_unknown_nodes_are_rejected():
    with pytest.raises(GraphError, match="unknown node 'ghost'"):
        graph.validate([TRIGGER, ACTION], [Edge("t", NodePort.OUT, "ghost")])


def test_nothing_may_feed_the_trigger():
    """A trigger has no input. An edge into one would make the graph's entry
    point depend on its own output."""
    nodes = [TRIGGER, ACTION]
    with pytest.raises(GraphError, match="nothing may feed the trigger"):
        graph.validate(nodes, [Edge("a", NodePort.OUT, "t")])


def test_duplicate_node_ids_are_rejected():
    with pytest.raises(GraphError, match="duplicate node id"):
        graph.validate([TRIGGER, _node("t", AutomationNodeKind.ACTION)], [])


def test_node_count_is_capped():
    nodes = [TRIGGER] + [_node(f"a{i}", AutomationNodeKind.ACTION) for i in range(MAX_GRAPH_NODES)]
    with pytest.raises(GraphError, match="at most"):
        graph.validate(nodes, [])


# --- traversal ---------------------------------------------------------------


def test_topological_order_puts_every_node_after_its_sources():
    nodes = [ACTION, FILTER, TRIGGER]  # deliberately not in execution order
    edges = [Edge("t", NodePort.OUT, "f"), Edge("f", NodePort.MATCHED, "a")]
    order = [n.id for n in graph.topological_order(nodes, edges)]
    assert order.index("t") < order.index("f") < order.index("a")


def test_order_is_deterministic_across_runs():
    """Side effects are applied in this order, so it cannot vary run to run —
    ties break on node id rather than on dict iteration luck."""
    nodes = [TRIGGER] + [_node(c, AutomationNodeKind.ACTION) for c in "zyx"]
    edges = [Edge("t", NodePort.OUT, c) for c in "zyx"]
    first = [n.id for n in graph.topological_order(nodes, edges)]
    assert first == [n.id for n in graph.topological_order(list(reversed(nodes)), edges)]


def test_parallel_edges_do_not_read_as_a_cycle():
    """Both ports of one filter feeding the same action is legal — 'do this
    either way, but only for items the filter saw'. Counting the edge on one
    side only would strand the target above indegree zero."""
    nodes = [TRIGGER, FILTER, ACTION]
    edges = [
        Edge("t", NodePort.OUT, "f"),
        Edge("f", NodePort.MATCHED, "a"),
        Edge("f", NodePort.UNMATCHED, "a"),
    ]
    graph.validate(nodes, edges)
    assert len(graph.topological_order(nodes, edges)) == 3


def test_unreachable_nodes_are_detectable():
    """A branch nobody wired to the trigger never runs. The editor needs to say
    so — a node that looks configured but is detached is the quietest way for an
    automation to do nothing."""
    orphan = _node("orphan", AutomationNodeKind.ACTION)
    nodes = [TRIGGER, ACTION, orphan]
    edges = [Edge("t", NodePort.OUT, "a")]
    reachable = graph.is_reachable(["t"], nodes, edges)
    assert reachable == {"t", "a"}
    assert "orphan" not in reachable


# --- packets -----------------------------------------------------------------


def test_fan_in_unions_and_deduplicates_preserving_order():
    one, two, three = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    left = Packet.of(None, item=(one, two))
    right = Packet.of(None, item=(two, three))
    assert left.merge(right).item_ids == (one, two, three)


def test_an_empty_packet_is_empty_but_still_a_packet():
    """Spec 116: an empty match does not halt the branch. The packet flows on and
    each node decides via needs_items — which is what keeps 'nothing matched,
    tell me' expressible."""
    packet = Packet.of(object(), item=())
    assert packet.is_empty
    assert packet.facts is not None


def test_with_items_deduplicates():
    dup = uuid.uuid4()
    assert Packet.of(None).with_items([dup, dup]).item_ids == (dup,)


# --- parsing -----------------------------------------------------------------


def test_parse_rejects_an_unknown_kind_naming_the_node():
    with pytest.raises(GraphError, match="node 'n1'"):
        graph.parse([{"id": "n1", "kind": "sideways", "type": "x"}], [])


def test_parse_rejects_a_node_without_a_type():
    with pytest.raises(GraphError, match="missing type"):
        graph.parse([{"id": "n1", "kind": "action"}], [])


def test_parse_round_trips_a_stored_graph():
    nodes, edges = graph.parse(
        [
            {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": "item.created"}},
            {"id": "a", "kind": "action", "type": "action.add_label", "params": {"label": "triage"}},
        ],
        [{"source": "t", "port": "out", "target": "a"}],
    )
    assert [n.id for n in nodes] == ["t", "a"]
    assert nodes[0].params == {"event": "item.created"}
    assert edges == [Edge("t", NodePort.OUT, "a")]


# --- template tokens: the catalogue and the resolver must agree ----------------


def test_every_documented_token_actually_resolves():
    """A token in the reference panel that the resolver does not know renders as
    a literal `{{…}}` in somebody's issue title — visible to them, invisible to
    us. The two live side by side in `templating.py` for this reason; this makes
    the pairing enforceable rather than a convention."""
    from radd.modules.automations import templating
    from radd.modules.automations.conditions import EventFacts

    facts = EventFacts(
        event_type="item.updated",
        actor_id="11111111-1111-1111-1111-111111111111",
        actor_email="a@b.c",
        actor_name="Ada",
        payload={"matched_count": 3, "changes": [{"field": "state"}]},
    )
    item_ctx = {"key": "TD-42", "title": "A title", "id": "22222222-2222-2222-2222-222222222222"}
    # The set an action speaks for — the executor always supplies it, so a token
    # that only resolves with items is still a resolving token.
    items = [item_ctx, {"key": "TD-43", "title": "Another", "id": "33333333-3333-3333-3333-333333333333"}]

    for info in templating.TOKENS:
        token = info.token
        if "<path>" in token:  # the documented shape, not a literal token
            token = "{{payload.changes.field}}"
        rendered = templating.render_template(token, facts, item_ctx, items)
        assert rendered != token, (
            f"{info.token} is documented but did not resolve — it would appear "
            f"verbatim in the output"
        )


def test_item_tokens_are_flagged_as_needing_an_item():
    """An itemless run (a schedule tick) cannot resolve item tokens, so the panel
    marks them — otherwise someone builds a title around a value that is always
    blank on their trigger."""
    from radd.modules.automations import templating

    needing = {info.token for info in templating.TOKENS if info.needs_item}
    assert needing == {"{{item.key}}", "{{item.title}}", "{{item.id}}"}
