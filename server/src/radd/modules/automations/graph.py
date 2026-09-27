"""The automation graph (spec 116): structure, validation and traversal. Pure —
no session or I/O; `executor.py` gives nodes their meaning.

* Cycles are rejected on WRITE, where the message can name the edge; at run
  time a cycle would hang the consumer.
* Empty sets propagate: a filter matching nothing does not halt its branch;
  each node's `needs_items` decides whether it runs, so "nothing matched —
  tell me" is expressible.
"""

from __future__ import annotations

import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Mapping

from radd.kernel.specs import ITEM_SUBJECT as KERNEL_ITEM_SUBJECT

from .types import (
    MAX_GRAPH_EDGES,
    MAX_GRAPH_NODES,
    MAX_GRAPH_TRIGGERS,
    PORTS_BY_KIND,
    AutomationNodeKind,
    NodePort,
)


class GraphError(ValueError):
    """A stored or submitted graph that cannot be executed. Carries a message
    written for the person editing the automation, not for a log."""


#: How a node's outputs are determined. The default is the KIND's fixed set;
#: the automations module passes a resolver backed by the node registry, so a
#: node type can name its own ports and derive them from its params — an AI
#: classifier with four user-defined answers has four outputs, which no
#: per-kind table can express.
PortsResolver = Callable[["Node"], tuple[str, ...]]


def default_ports(node: "Node") -> tuple[str, ...]:
    return tuple(port.value for port in PORTS_BY_KIND[node.kind])


@dataclass(frozen=True)
class Node:
    id: str
    kind: AutomationNodeKind
    type: str  # the node-type key: "filter.slq", "action.create_item", …
    params: dict[str, Any] = field(default_factory=dict)
    #: What downstream tokens call this node (spec 120) — prose, freely renamable,
    #: unlike `id`, which edges wire to. Held verbatim; an illegal name makes the
    #: node unaddressable, never the graph unloadable.
    name: str = ""


@dataclass(frozen=True)
class Edge:
    source: str
    #: A PLAIN STRING, not `NodePort` (RADD-918). Coercing it through the enum
    #: made the five built-in names the only wireable ports in existence, so a
    #: contributed node's dynamic outputs — an AI classifier's answers, which is
    #: the entire reason `ports_for(params)` exists — were rejected by `parse`
    #: before `validate` ever got to check them against the real set. `validate`
    #: is what makes a port name legal, and it asks the node.
    port: str
    target: str


#: The subject every built-in node acts on — the kernel's, because
#: `packet.item_ids` and `AutomationNodeSpec.subject`'s default have to agree.
ITEM_SUBJECT = KERNEL_ITEM_SUBJECT


@dataclass(frozen=True)
class Packet:
    """What travels along an edge: event `facts` plus entity IDS per subject
    (RADD-923) — never ORM rows, which would tie this module to a session.
    Ordered and deduplicated per subject, because the order side effects apply
    in is observable (comments, webhook bodies)."""

    facts: Any  # conditions.EventFacts — typed there, kept opaque to stay pure
    subjects: Mapping[str, tuple[uuid.UUID, ...]] = field(default_factory=dict)
    #: The VARIABLE BAG (spec 120): node name -> what it produced, as strings.
    #: On the packet, not the run, so a value from an untaken branch is unreadable.
    #: Inner dicts are replaced, never mutated, so packets may share them.
    vars: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    @classmethod
    def of(cls, facts: Any, **subjects: Iterable[uuid.UUID]) -> Packet:
        """`Packet.of(facts, item=[id])`."""
        return cls(facts=facts, subjects={k: _dedupe(v) for k, v in subjects.items()})

    @property
    def item_ids(self) -> tuple[uuid.UUID, ...]:
        return tuple(self.subjects.get(ITEM_SUBJECT, ()))

    def ids_of(self, subject: str) -> tuple[uuid.UUID, ...]:
        """Ids of one entity type — what a node's declared `subject` resolves to."""
        return tuple(self.subjects.get(subject, ()))

    @property
    def is_empty(self) -> bool:
        """Emptiness is about ITEMS. Every node that asks is an item node; a
        subject-typed node asks `ids_of` and decides for itself."""
        return not self.item_ids

    def with_items(self, item_ids: Iterable[uuid.UUID]) -> Packet:
        return self.with_subject(ITEM_SUBJECT, item_ids)

    def with_subject(self, subject: str, ids: Iterable[uuid.UUID]) -> Packet:
        """Replace ONE subject, keeping the others. A filter narrows the items an
        event is about without forgetting which release it was about."""
        return replace(self, subjects={**self.subjects, subject: _dedupe(ids)})

    def with_vars(self, name: str, values: Mapping[str, str]) -> Packet:
        """What a node PRODUCED, filed under the name it is addressed by.

        An unnamed producer returns the packet unchanged: it ran, it just has no
        handle, and inventing one from the node id would make `{{act3.key}}` a
        token nobody wrote and nothing offered.
        """
        if not name or not values:
            return self
        return replace(
            self,
            vars={**self.vars, name: {key: str(value) for key, value in values.items()}},
        )

    def merge(self, other: Packet) -> Packet:
        """Fan-in, per subject. `facts` are identical by construction (one run).
        Variables union with the LATER writer winning, and `walk` merges in
        topological order, so "later" is the producer that ran second."""
        merged = {
            key: _dedupe(self.subjects.get(key, ()) + other.subjects.get(key, ()))
            for key in {*self.subjects, *other.subjects}
        }
        return replace(self, subjects=merged, vars={**self.vars, **other.vars})


def _dedupe(item_ids: Iterable[uuid.UUID]) -> tuple[uuid.UUID, ...]:
    """Order-preserving. dict.fromkeys rather than a set, because the order items
    are acted on is observable — comments land in it, and so do webhook bodies."""
    return tuple(dict.fromkeys(item_ids))


# --- parsing -----------------------------------------------------------------


def parse(nodes: Iterable[Mapping[str, Any]], edges: Iterable[Mapping[str, Any]]) -> tuple[list[Node], list[Edge]]:
    """Raw JSONB -> typed. Raises GraphError on anything malformed, so callers
    downstream may assume the shapes."""
    parsed_nodes: list[Node] = []
    for raw in nodes:
        try:
            kind = AutomationNodeKind(raw["kind"])
        except (KeyError, ValueError) as exc:
            raise GraphError(f"node {raw.get('id', '?')!r}: unknown kind {raw.get('kind')!r}") from exc
        node_id = str(raw.get("id") or "")
        if not node_id:
            raise GraphError("every node needs an id")
        node_type = str(raw.get("type") or "")
        if not node_type:
            raise GraphError(f"node {node_id!r}: missing type")
        params = raw.get("params") or {}
        if not isinstance(params, dict):
            raise GraphError(f"node {node_id!r}: params must be an object")
        parsed_nodes.append(
            Node(
                id=node_id,
                kind=kind,
                type=node_type,
                params=dict(params),
                # Read leniently — a stored name that is not a legal identifier
                # makes the node unaddressable, never unloadable (spec 120).
                name=str(raw.get("name") or ""),
            )
        )

    parsed_edges: list[Edge] = []
    for raw in edges:
        # Whether the name is a REAL port is `validate`'s question, because only
        # the node knows — see Edge.port.
        port = str(raw.get("port") or NodePort.OUT.value)
        source, target = str(raw.get("source") or ""), str(raw.get("target") or "")
        if not source or not target:
            raise GraphError("every edge needs a source and a target")
        parsed_edges.append(Edge(source=source, port=port, target=target))
    return parsed_nodes, parsed_edges


# --- validation --------------------------------------------------------------


def validate(
    nodes: list[Node], edges: list[Edge], ports_of: PortsResolver = default_ports
) -> list[Node]:
    """Check a graph and return its TRIGGERS; raises GraphError naming the node or
    edge. Several triggers are legal ("on create OR every Monday"), and so is zero
    (a graph mid-build is saved before it is wired; it simply never runs)."""
    if len(nodes) > MAX_GRAPH_NODES:
        raise GraphError(f"a graph may hold at most {MAX_GRAPH_NODES} nodes ({len(nodes)} given)")
    if len(edges) > MAX_GRAPH_EDGES:
        raise GraphError(f"a graph may hold at most {MAX_GRAPH_EDGES} edges ({len(edges)} given)")

    by_id: dict[str, Node] = {}
    for node in nodes:
        if node.id in by_id:
            raise GraphError(f"duplicate node id {node.id!r}")
        by_id[node.id] = node

    triggers = [n for n in nodes if n.kind is AutomationNodeKind.TRIGGER]
    if len(triggers) > MAX_GRAPH_TRIGGERS:
        raise GraphError(
            f"a graph may hold at most {MAX_GRAPH_TRIGGERS} triggers ({len(triggers)} given)"
        )

    for edge in edges:
        source = by_id.get(edge.source)
        if source is None:
            raise GraphError(f"edge from unknown node {edge.source!r}")
        if edge.target not in by_id:
            raise GraphError(f"edge to unknown node {edge.target!r}")
        allowed = ports_of(source)
        if edge.port not in allowed:
            raise GraphError(
                f"node {edge.source!r} ({source.kind.value}) has no '{edge.port}' port — "
                f"it emits {', '.join(allowed)}"
            )
        if by_id[edge.target].kind is AutomationNodeKind.TRIGGER:
            raise GraphError(f"nothing may feed the trigger {edge.target!r}")

    _reject_cycles(nodes, edges)
    return triggers


def _reject_cycles(nodes: list[Node], edges: list[Edge]) -> None:
    """Kahn's algorithm; whatever it cannot drain is in (or fed by) a cycle."""
    order = _kahn(nodes, edges)
    if len(order) != len(nodes):
        stuck = sorted({n.id for n in nodes} - {n.id for n in order})
        raise GraphError("these nodes form a cycle: " + ", ".join(stuck))


def _kahn(nodes: list[Node], edges: list[Edge]) -> list[Node]:
    indegree: dict[str, int] = {n.id: 0 for n in nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        # Parallel edges (two ports of one filter feeding the same node) are
        # counted on both sides — indegree += 1 here, one decrement from the
        # matching entry in `outgoing` — so they balance rather than stranding
        # the target above zero and reading as a false cycle.
        outgoing[edge.source].append(edge.target)
        indegree[edge.target] += 1

    queue = deque(sorted((n.id for n in nodes if indegree[n.id] == 0)))
    by_id = {n.id: n for n in nodes}
    order: list[Node] = []
    while queue:
        current = queue.popleft()
        order.append(by_id[current])
        for target in outgoing[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    return order


def topological_order(nodes: list[Node], edges: list[Edge]) -> list[Node]:
    """Execution order. Deterministic — ties break on node id, so two runs over
    the same graph apply their side effects in the same sequence."""
    order = _kahn(nodes, edges)
    if len(order) != len(nodes):  # validate() should have caught this on write
        raise GraphError("graph contains a cycle")
    return order


def inbound(edges: list[Edge]) -> dict[str, list[Edge]]:
    """target id -> the edges feeding it."""
    result: dict[str, list[Edge]] = defaultdict(list)
    for edge in edges:
        result[edge.target].append(edge)
    return result


def is_reachable(trigger_ids: Iterable[str], edges: list[Edge]) -> set[str]:
    """Ids reachable from ANY trigger. A node outside this set never runs — the
    editor should say so rather than leave someone waiting on a detached branch.

    Takes a set because a graph may have several triggers, and a node fed only by
    the Monday schedule is still live even though the create trigger cannot reach
    it."""
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        outgoing[edge.source].append(edge.target)
    seen = set(trigger_ids)
    queue = deque(seen)
    while queue:
        for target in outgoing[queue.popleft()]:
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen
