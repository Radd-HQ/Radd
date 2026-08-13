"""The automation graph (spec 116): structure, validation and traversal.

An automation is a DAG. A TRIGGER emits a packet of `(event facts, item set)`;
FILTER narrows the set and splits it across `matched`/`unmatched`; GATE routes the
whole packet by a boolean over the event, leaving the set untouched; ACTION does
work and passes its input through so chains continue.

Pure module — no session, no I/O, no service calls. It answers "is this graph
legal" and "in what order do its nodes run", and the engine supplies the meaning
of each node. That is the same split `conditions.py` uses, and it is what makes
both unit-testable without a database.

Two rules that are enforced here rather than hoped for:

* **Cycles are rejected on WRITE.** A cycle found at run time is a hung consumer;
  found on write it is a validation message next to the edge that caused it.
* **Empty sets propagate.** A filter matching nothing does not halt its branch —
  the packet flows on carrying an empty set, and each node decides via
  `needs_items` whether it runs. Halting would be the simpler rule and was
  rejected: universal actions (webhook, email, chat) run itemless BY DESIGN
  today, and "nothing matched, tell me" is a real automation that halting makes
  inexpressible.
"""

from __future__ import annotations

import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Mapping

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
    #: What downstream nodes CALL this one (spec 120) — the left half of
    #: `{{triage.priority}}`. Optional: a node with no name still runs, it just
    #: cannot be addressed, which is the right answer for the fourteen node types
    #: that produce nothing.
    #:
    #: Separate from `id` on purpose. The id is machinery — `act3`, `gate1` — and
    #: is what edges are wired to, so renaming it would break every edge; a name
    #: is prose someone chose and can change freely. Conflating them would make
    #: "call this triage" a graph-wide rewire.
    #:
    #: Held VERBATIM. Whether it is a legal name is `nodes.output_name` /
    #: the write path's question: a stored name that is not legal degrades to
    #: unaddressable rather than making the automation unloadable.
    name: str = ""

    @property
    def ports(self) -> tuple[NodePort, ...]:
        """The KIND's fixed ports. Callers that must honour a node type's own
        outputs use the resolver passed to `validate` instead — this stays for
        the kinds whose ports genuinely are fixed."""
        return PORTS_BY_KIND[self.kind]


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


#: The subject every built-in node acts on. Named rather than inlined because
#: `packet.item_ids` and `AutomationNodeSpec.subject`'s default have to agree.
ITEM_SUBJECT = "item"


@dataclass(frozen=True)
class Packet:
    """What travels along an edge.

    IDS, never rows — the engine loads them, and a packet carrying ORM objects
    would tie this module to a session. `facts` rides along because actions
    template `{{tokens}}` off the event and gates evaluate on it; an ids-only
    edge would break both.

    **Subjects, plural (RADD-923).** A packet carries ids per ENTITY TYPE, not
    just items: an event about a deployment can name the deployment, the release
    and the item at once, and a contributed action node declaring
    `subject="deployment"` is handed exactly those ids. `item_ids` remains as a
    property because items are what every built-in node acts on, and reading
    `packet.subjects["item"]` at ninety call sites would say nothing extra.

    Ordered and deduplicated per subject: fan-in unions two branches, and without
    an order the actions applied downstream would vary run to run.
    """

    facts: Any  # conditions.EventFacts — typed there, kept opaque to stay pure
    subjects: Mapping[str, tuple[uuid.UUID, ...]] = field(default_factory=dict)
    #: The VARIABLE BAG (spec 120): node name -> what that node produced, as
    #: strings. It rides on the packet rather than on the run because branching
    #: is what makes it interesting — a value produced on one branch must not be
    #: readable on a branch that never ran, which a run-wide dict could not
    #: express.
    #:
    #: **Aliasing.** The outer dict is rebuilt on every write (`with_vars`) and
    #: the inner dicts are only ever REPLACED, never mutated in place — so a
    #: packet handed to three downstream nodes shares its inner mappings safely
    #: and copying them would buy nothing. Values are strings because that is
    #: what a `{{token}}` renders to; a producer stringifies at the seam rather
    #: than every consumer guessing.
    vars: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    @classmethod
    def of(cls, facts: Any, **subjects: Iterable[uuid.UUID]) -> Packet:
        """`Packet.of(facts, item=[id])` — the constructor for the common case.

        A classmethod rather than an `item_ids=` kwarg because items stopped
        being the only subject, and a keyword that privileges one entity type is
        how the rest of them end up second-class."""
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
        """Fan-in, per subject. Safe to keep `self.facts`: both packets come from
        the same run, so their facts are identical by construction — there is no
        reconciling to do, and asserting equality here would be checking the
        engine, not the graph.

        Variables union with the LATER writer winning, and `walk` feeds the
        arriving packets in topological order so "later" means "the producer that
        ran second". Two branches that both name a node `triage` is a graph the
        write path refuses, so in practice this only unions disjoint bags — the
        rule exists so the one case that can still collide (the same producer
        reached twice by different routes) resolves the same way on every run.
        """
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
    """Check a graph and return its TRIGGERS. Raises GraphError with a message
    naming the offending node or edge.

    Several triggers are legal, and zero is too:

    * **Several** — "when an item is created, OR every Monday" is one automation
      with one set of actions, not two graphs kept in step by hand. A firing
      event starts the run at the trigger that matched; the others do not emit.
    * **Zero** — a graph being built is saved before it is wired. It simply never
      runs, which the editor says out loud rather than the API refusing to store
      work in progress.
    """
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


def is_reachable(trigger_ids: Iterable[str], nodes: list[Node], edges: list[Edge]) -> set[str]:
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
