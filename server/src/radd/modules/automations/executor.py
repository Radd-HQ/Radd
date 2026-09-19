"""Walking an automation graph (spec 116).

`graph.py` says whether a graph is legal and in what order its nodes run. This
module says what each node MEANS: a gate evaluates event conditions, a filter
compiles SLQ and splits the item set, an action plans and applies.

The split matters because the walk is the part with I/O — sessions, the SLQ
compiler, the target services — and keeping it out of `graph.py` is what lets the
structure rules be unit-tested without a database.

Two invariants live here rather than in the caller:

* **Budget.** A linear rule cost `items x actions`; a graph costs
  `items x nodes x fan-out`. `RunBudget` caps node executions and item-actions,
  and a run that hits a cap **records what it dropped**. A cap that truncates
  silently makes a run that did less look identical to a run that had less to do.
* **Best-effort per action.** Each action still runs inside a SAVEPOINT, so one
  failing action rolls back only itself and the walk continues — the behaviour
  `_run_rule_actions` had before graphs, kept because the alternative is one bad
  webhook URL stopping every downstream branch.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field, replace
from time import monotonic
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.items.models import WorkItem
from radd.modules.events import service as events
from radd.modules.projects.models import Project
from radd.modules.fields.validation import FieldValidationError
from radd.modules.workflow.guards import TransitionError

from radd.kernel.specs import valid_output_name

from . import graph
from .gates import GATE_EVALUATORS
from .nodes import arity_of, needs_items, output_name, ports_of, spec_for
from .graph import Edge, Node, Packet
# Node-type keys live in `types.py` — the schemas and the arity table name them
# too, and a type spelled differently in two places is a wire constant with no
# compiler behind it. Imported (not redefined) so `executor.ACTION_TYPE_PREFIX`
# keeps resolving for existing callers.
from .types import (  # noqa: F401 — re-exported for callers importing them here
    ACTION_TYPE_PREFIX,
    TYPE_FILTER_SLQ,
    TYPE_SEARCH_SLQ,
    TYPE_VALIDATION_FAIL,
    AutomationNodeKind,
    AutomationTrigger,
    NodeArity,
    NodePort,
    PlanKind,
    SearchMode,
)

logger = logging.getLogger(__name__)


@dataclass
class RunBudget:
    """What a single graph run is allowed to spend, and what it had to drop."""

    max_nodes: int
    max_item_actions: int
    nodes_run: int = 0
    item_actions_run: int = 0
    dropped: list[str] = field(default_factory=list)

    def take_node(self, node: Node) -> bool:
        if self.nodes_run >= self.max_nodes:
            self.dropped.append(f"node {node.id!r} ({node.type}) — node budget {self.max_nodes} reached")
            return False
        self.nodes_run += 1
        return True

    def take_item_actions(self, node: Node, count: int) -> int:
        """How many of `count` item-actions this node may run. Returns 0..count,
        recording the shortfall rather than trimming in silence."""
        remaining = max(0, self.max_item_actions - self.item_actions_run)
        allowed = min(count, remaining)
        if allowed < count:
            self.dropped.append(
                f"node {node.id!r} ({node.type}) — {count - allowed} of {count} items skipped, "
                f"item-action budget {self.max_item_actions} reached"
            )
        self.item_actions_run += allowed
        return allowed

    @property
    def exhausted(self) -> bool:
        return self.nodes_run >= self.max_nodes or self.item_actions_run >= self.max_item_actions


def new_budget() -> RunBudget:
    return RunBudget(
        max_nodes=settings.automation_graph_max_node_runs,
        max_item_actions=settings.automation_graph_max_item_actions,
    )


@dataclass(frozen=True)
class Finding:
    """One thing wrong with the draft a validation walk is inspecting (spec 119).

    `field` names the control the person should go and fix — a builtin field name
    (`title`, `description`, `assignee`) or `cf.<key>` — and is empty for a
    finding about the submission as a whole. It is validated LOOSELY and against
    nothing here: a graph written when a custom field existed keeps producing
    readable advice after it is deleted, it just stops highlighting a control.
    `node_id` is kept so the run report can say which check spoke.

    `mode` is the VALIDATION MODE of the graph that produced it, stamped by
    `validation.run_graphs` and empty on every other walk. It rides on the
    finding rather than on the verdict because a draft is routinely governed by
    several graphs at once: aggregating the mode and then asking "are there
    findings" refuses a submission that satisfied every REQUIRED graph and only
    tripped an advisory one — which `POST /items` would have accepted.
    """

    node_id: str
    message: str
    field: str = ""
    mode: str = ""


@dataclass
class PlannedAction:
    """One action a node resolved, before it was (or was not) applied."""

    node_id: str
    action_type: str
    params: dict
    item_id: uuid.UUID | None
    resolves: bool  # False = the planner returned SKIP (a named target has gone)
    detail: str
    #: `{{token}}` -> what it rendered to on this invocation (spec 120). Only the
    #: params that actually CARRIED a token appear, so the dry run can show
    #: `{{triage.priority}} → high` without repeating every literal beside it.
    resolved: dict[str, str] = field(default_factory=dict)
    #: True when the apply was REFUSED by a workflow guard or the field registry
    #: (RADD-1266) — a skip with a different owner: the project's rules said no,
    #: not the planner. The run history ranks it above "applied".
    refused: bool = False


@dataclass
class RunReport:
    """What the walk did — per node, so a dry run can show where items went and a
    real run can explain itself. `dropped` is the budget's, surfaced not buried.

    `plans` is collected whether or not the run applied. That is what makes the
    dry run free rather than a second implementation: the same code decides, and
    only the applying is switched off."""

    per_node: dict[str, dict[str, int]] = field(default_factory=dict)
    plans: list[PlannedAction] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    #: node id -> ports that did not fire at all this run. Distinct from a port
    #: that fired with zero items; the editor renders them differently because
    #: they mean different things.
    not_taken: dict[str, list[str]] = field(default_factory=dict)
    #: node id -> port -> the item ids that LEFT by it, capped. Counts alone
    #: answer "did my filter narrow anything"; they cannot answer "did it keep
    #: the right ones", which is the question someone debugging a graph actually
    #: has. Ids rather than keys: this module never loads an item it does not
    #: need, and the caller resolves keys once for the whole report.
    port_items: dict[str, dict[str, tuple[uuid.UUID, ...]]] = field(default_factory=dict)
    #: node id -> what ARRIVED, capped the same way.
    incoming_items: dict[str, tuple[uuid.UUID, ...]] = field(default_factory=dict)
    #: What the walk found wrong (spec 119), in the order the checks ran. Only
    #: ever filled when `collecting` is true — see below.
    findings: list[Finding] = field(default_factory=list)
    #: node id -> the values that node PRODUCED (spec 120). Recorded whether or
    #: not the node was NAMED: an unnamed producer is exactly the mistake a dry
    #: run should show, and hiding its output would leave "why does my token not
    #: resolve" unanswerable from the report.
    produced: dict[str, dict[str, str]] = field(default_factory=dict)
    #: THE WALK'S OWN SETTINGS, carried on the report because every node handler
    #: already receives it and threading a second object through nine signatures
    #: would buy nothing.
    #:
    #: `collecting` is true exactly when the graph was entered through a
    #: `validate` trigger. Findings are that trigger's whole output; anywhere
    #: else there is nobody to show them to, so `add_finding` is a no-op and
    #: `validation.fail` stays quiet — which is what makes `ai.validate` a pure
    #: pass/fail router on an ordinary event walk, as the spec has always
    #: claimed and the code did not do. A validate-trigger graph run MANUALLY or
    #: previewed still collects: same trigger, same question, and the rule test
    #: panel exists to show the answer.
    collecting: bool = False
    #: `time.monotonic()` past which a check that costs real time (a model round
    #: trip) should give up and take its unavailable path. Set only by the
    #: intake path, where the walk runs inside a request holding a row lock.
    deadline: float | None = None

    def record(self, node: Node, packet: Packet, outgoing: dict[str, Packet]) -> None:
        self.per_node[node.id] = {
            "in": len(packet.item_ids),
            **{str(port): len(out.item_ids) for port, out in outgoing.items()},
        }
        self.incoming_items[node.id] = packet.item_ids[:SAMPLE_ITEMS]
        self.port_items[node.id] = {
            str(port): out.item_ids[:SAMPLE_ITEMS] for port, out in outgoing.items()
        }

    def untaken(self, node: Node, ports: list[str]) -> None:
        if ports:
            self.not_taken[node.id] = ports


#: How many item ids a report keeps per port. Enough to recognise what came
#: through, small enough that a 200-item scheduled run does not build a report
#: bigger than the work it describes — the count beside it is always exact.
SAMPLE_ITEMS = 10

#: What a `validation.fail` node with no message says. Only reachable from a
#: hand-edited row — the write path requires one.
UNSPOKEN_FINDING = "This submission did not pass a check (the check has no message set)."


async def walk(
    session: AsyncSession,
    *,
    nodes: list[Node],
    edges: list[Edge],
    trigger: Node,
    initial: Packet,
    system_user: User,
    automation_name: str,
    budget: RunBudget,
    apply: bool = True,
    deadline: float | None = None,
) -> RunReport:
    """Execute the graph. `apply=False` plans without applying — the dry-run path,
    which is only free because a node plans before it applies.

    Whether the walk COLLECTS findings is read off the trigger it starts from
    rather than passed in: a walk entered through a `validate` trigger is asking
    a question, and every other walk is doing a job. Deriving it here is what
    keeps the two callers from disagreeing about it.
    """
    report = RunReport(
        collecting=str(trigger.params.get("event") or "") == AutomationTrigger.VALIDATE.value,
        deadline=deadline,
    )
    order = graph.topological_order(nodes, edges)
    inbound = graph.inbound(edges)
    #: Where each node sits in the run. Fan-in merges its feeders in THIS order
    #: (spec 120) rather than in the order the edges happen to be stored, so
    #: "the later producer's variables win" means the one that actually ran
    #: second — and so two saves of the same graph cannot merge differently.
    rank = {node.id: index for index, node in enumerate(order)}

    #: (node id, port) -> what that port emitted. One key space, so a node id can
    #: never be confused with a port of the same name.
    #:
    #: A port MISSING from this map is not the same as one that emitted an empty
    #: packet, and the difference is the whole of branch semantics: a gate emits
    #: only the port it took, so the branch it did not take never runs, while a
    #: filter emits both because an empty subset is a real answer ("nothing
    #: matched — tell me"). Before RADD-918 a gate emitted an empty packet on the
    #: untaken port, so a `send_email` wired to `false` fired on every run where
    #: the gate PASSED — universal actions ignore emptiness by design.
    emitted: dict[tuple[str, str], Packet] = {}

    for node in order:
        if node.id == trigger.id:
            packet = initial
        else:
            feeding = sorted(
                (
                    edge
                    for edge in inbound.get(node.id, [])
                    if (edge.source, edge.port) in emitted
                ),
                key=lambda edge: (rank.get(edge.source, 0), edge.port),
            )
            arriving = [emitted[(edge.source, edge.port)] for edge in feeding]
            if not arriving:
                continue  # detached from the trigger, or every feeder ran out of budget
            packet = arriving[0]
            for extra in arriving[1:]:
                packet = packet.merge(extra)

        if not budget.take_node(node):
            break

        outputs = await _run_node(
            session,
            node=node,
            packet=packet,
            system_user=system_user,
            automation_name=automation_name,
            budget=budget,
            apply=apply,
            report=report,
        )
        report.record(node, packet, outputs)
        for port, out_packet in outputs.items():
            emitted[(node.id, port)] = out_packet
        # Ports the node did NOT emit are recorded as untaken, so the editor can
        # grey the branch rather than showing it as "0 items" — which reads as
        # "it ran and found nothing".
        report.untaken(node, [p for p in ports_of(node) if p not in outputs])

    report.dropped = list(budget.dropped)
    if report.dropped:
        logger.warning(
            "automations: %s hit a run budget; %s", automation_name, "; ".join(report.dropped)
        )
    return report


async def _run_node(
    session: AsyncSession,
    *,
    node: Node,
    packet: Packet,
    system_user: User,
    automation_name: str,
    budget: RunBudget,
    apply: bool,
    report: RunReport,
) -> dict[str, Packet]:
    """One node, dispatched on two axes rather than four special cases
    (RADD-918): what the node DOES (produce / route / act) and how it reads its
    packet (`NodeArity`). Filter-vs-gate and item-action-vs-universal-action were
    the same distinction written twice."""
    if node.kind is AutomationNodeKind.TRIGGER:
        return {NodePort.OUT.value: packet}

    if node.kind is AutomationNodeKind.SOURCE:
        return {NodePort.OUT.value: await _run_source(session, node, packet, automation_name)}

    if node.kind in (AutomationNodeKind.GATE, AutomationNodeKind.FILTER):
        return await _run_router(session, node, packet, system_user, report)

    created, produced = await _run_action(
        session,
        node=node,
        packet=packet,
        system_user=system_user,
        automation_name=automation_name,
        budget=budget,
        apply=apply,
        report=report,
    )
    # An action passes its INPUT through unchanged, which is what makes chains
    # work: filter -> label -> comment all act on the same set. What it MADE
    # leaves by a separate port, so "create a follow-up, then assign it" is a
    # wire rather than a special case.
    passthrough = _stamp(node, packet, produced, report)
    outputs = {NodePort.OUT.value: passthrough}
    if NodePort.CREATED.value in ports_of(node):
        outputs[NodePort.CREATED.value] = passthrough.with_items(created)
    return outputs


def _stamp(
    node: Node, packet: Packet, produced: dict[str, str], report: RunReport
) -> Packet:
    """The packet a producing node emits: its input, plus what it produced under
    the node's NAME (spec 120).

    On EVERY port it emits, not only on one. `create_item`'s `out` carries the
    items that caused the new issue and `created` carries the new issue itself —
    both are places someone legitimately wants `{{followup.key}}`, and a rule
    that put the values on one of them would make which one a thing to remember.

    Recorded in the report either way; stamped only when the node has a usable
    name, because a bag keyed by node id would be a token nobody wrote.
    """
    if not produced:
        return packet
    report.produced[node.id] = dict(produced)
    return packet.with_vars(output_name(node), produced)


# --- sources: the only nodes that PRODUCE items ------------------------------


async def _run_source(
    session: AsyncSession, node: Node, packet: Packet, automation_name: str
) -> Packet:
    """Run a search node's query and emit what it found."""
    if node.type != TYPE_SEARCH_SLQ:
        logger.error("automations: %s: unknown source node type %r", automation_name, node.type)
        return packet.with_items(())

    from . import search  # deferred: search reaches into planning's helpers

    try:
        found = await search.find_items(
            session,
            str(node.params.get("slq") or ""),
            project_key=str(node.params.get("project") or ""),
            label=f"{automation_name} / {node.id}",
        )
    except Exception:
        # A query that no longer compiles (a custom field was deleted) must not
        # take the whole automation down — it emits nothing, which the run report
        # shows as a source that found zero.
        logger.exception("automations: %s: search node %s failed", automation_name, node.id)
        return packet.with_items(())

    mode = str(node.params.get("mode") or SearchMode.REPLACE.value)
    if mode == SearchMode.ADD.value:
        return packet.with_items((*packet.item_ids, *found))
    return packet.with_items(found)


# --- routers: gates and filters, which differ only in how they read the packet ---


async def _run_router(
    session: AsyncSession, node: Node, packet: Packet, actor: User, report: RunReport
) -> dict[str, Packet]:
    """Send the packet down one port, or split it across all of them.

    * **SET arity — ROUTE.** One answer for the whole packet, which leaves by one
      port. The other ports emit NOTHING, so the branches not taken do not run.
    * **ITEM arity — PARTITION.** Each item leaves by the port its own answer
      names. Every port emits, including the empty ones: a subset of nothing is
      a real answer, and "and for everything else…" is how the unmatched port
      has always worked.
    """
    ports = ports_of(node)
    if arity_of(node) is NodeArity.SET:
        chosen, produced = await _route(session, node, packet, actor, report)
        if chosen not in ports:
            logger.error(
                "automations: node %s (%s) chose port %r, which it does not emit", node.id, node.type, chosen
            )
            return {}
        return {chosen: _stamp(node, packet, produced, report)}

    assigned = await _partition(session, node, packet, actor, report)
    return {
        port: packet.with_items([i for i in packet.item_ids if assigned.get(i) == port])
        for port in ports
    }


async def _route(
    session: AsyncSession, node: Node, packet: Packet, actor: User, report: RunReport
) -> tuple[str, dict[str, str]]:
    """The single port a SET-arity router sends its packet down, and whatever it
    produced on the way (spec 120).

    A pair rather than a port, because a routing node is exactly where values are
    produced: `ai.classify` names the answer it chose, `ai.generate` names every
    field it filled in. A built-in gate produces nothing and says so with an
    empty mapping.
    """
    spec = spec_for(node)
    if spec is not None and spec.plan is not None:
        return await _run_registered_gate(session, node, packet, actor, report)

    evaluator = GATE_EVALUATORS.get(node.type)
    if evaluator is None:
        # A gate this build does not know — most often a plugin that has been
        # uninstalled. FALSE rather than a guess, and said out loud.
        logger.error("automations: node %s: unknown gate type %r", node.id, node.type)
        return NodePort.FALSE.value, {}
    passed = evaluator(packet.facts, node.params)
    return (NodePort.TRUE if passed else NodePort.FALSE).value, {}


async def _partition(
    session: AsyncSession, node: Node, packet: Packet, actor: User, report: RunReport
) -> dict[uuid.UUID, str]:
    """item id -> the port it leaves by, for an ITEM-arity router."""
    if packet.is_empty:
        return {}

    spec = spec_for(node)
    if spec is not None:
        return await _partition_registered(session, node, packet, actor, spec, report)
    if node.type == TYPE_FILTER_SLQ:
        return await _partition_slq(session, node, packet)
    logger.error("automations: node %s (%s) cannot run per item", node.id, node.type)
    return {}


async def _partition_slq(
    session: AsyncSession, node: Node, packet: Packet
) -> dict[uuid.UUID, str]:
    """The SLQ filter: matched / unmatched. An empty query matches everything,
    which is what a half-built filter should do — narrow nothing, not drop
    everything."""
    from .planning import condition_matches  # deferred: planning imports this module's siblings

    text = str(node.params.get("slq") or "").strip()
    if not text:
        return {item_id: NodePort.MATCHED.value for item_id in packet.item_ids}

    assigned: dict[uuid.UUID, str] = {}
    for item, project in await _load(session, packet.item_ids):
        if project is None:
            assigned[item.id] = NodePort.UNMATCHED.value
            continue
        try:
            hit = await condition_matches(session, text, item, project)
        except Exception:
            logger.exception("automations: filter %s failed on item %s", node.id, item.id)
            hit = False
        assigned[item.id] = (NodePort.MATCHED if hit else NodePort.UNMATCHED).value
    return assigned


async def _partition_registered(
    session: AsyncSession, node: Node, packet: Packet, actor: User, spec, report: RunReport
) -> dict[uuid.UUID, str]:
    """Ask a CONTRIBUTED router for each item's port.

    `plan_items` when the node has one — a node that knows its per-item work
    batches or parallelises should say so itself, because the executor shares one
    session across the walk and cannot safely run those calls concurrently on its
    behalf. Otherwise `plan` once per single-item packet, which is correct for
    any node and is the whole feature for a cheap one.
    """
    ports = spec.ports_at(node.params)
    if not ports:
        return {}
    fallback = ports[-1]

    if spec.plan_items is not None:
        try:
            answers = await spec.plan_items(
                _context(report, session=session, node=node, packet=packet, actor=actor)
            )
        except Exception:
            logger.exception(
                "automations: node %s (%s) failed per-item; taking its fallback port",
                node.id, node.type,
            )
            return {item_id: fallback for item_id in packet.item_ids}
        return {
            item_id: (str(answers.get(item_id)) if str(answers.get(item_id)) in ports else fallback)
            for item_id in packet.item_ids
        }

    if spec.plan is None:
        return {item_id: fallback for item_id in packet.item_ids}
    # The produced values are DROPPED at item arity, deliberately (spec 120).
    # Each item has its own answer, and the bag has one slot per node name — so
    # `{{classify.answer}}` could only ever name one of them, silently. A token
    # that misses is recorded and skips the action; a token that resolves to
    # some other item's answer is a wrong write nobody would notice.
    return {
        item_id: (
            await _run_registered_gate(
                session, node, packet.with_items((item_id,)), actor, report
            )
        )[0]
        for item_id in packet.item_ids
    }


async def _load(
    session: AsyncSession, item_ids: tuple[uuid.UUID, ...]
) -> list[tuple[WorkItem, Project | None]]:
    """Items with their projects, in the packet's order — the order is observable
    (comments land in it), so it is not left to the database."""
    if not item_ids:
        return []
    rows = (
        await session.execute(
            select(WorkItem, Project)
            .outerjoin(Project, Project.id == WorkItem.project_id)
            .where(WorkItem.id.in_(item_ids))
        )
    ).all()
    by_id = {item.id: (item, project) for item, project in rows}
    return [by_id[i] for i in item_ids if i in by_id]


async def _run_registered_gate(
    session: AsyncSession, node: Node, packet: Packet, actor: User, report: RunReport
) -> tuple[str, dict[str, str]]:
    """Ask a contributed gate which port the packet leaves by, and collect
    whatever it produced (spec 120).

    Failures return the spec's LAST port — every contributed gate declares a
    fallback as its final port for exactly this — rather than raising, so one
    unreachable provider cannot stop a graph that has other branches. A failure
    also produces NOTHING, which is what makes an outage safe downstream: the
    tokens that would have read its values miss and their actions skip, rather
    than resolving to whatever the previous run left behind.
    """
    spec = spec_for(node)
    ports = spec.ports_at(node.params) if spec else ()
    if not spec or not spec.plan or not ports:
        return "", {}
    if packet.is_empty and needs_items(node):
        # The node said it has nothing to say about no items. Its fallback port
        # rather than a guess, and rather than an unanswerable question sent to
        # whatever service it wraps.
        return ports[-1], {}
    ctx = _context(report, session=session, node=node, packet=packet, actor=actor)
    try:
        chosen = await spec.plan(ctx)
    except Exception:
        logger.exception("automations: node %s (%s) failed; taking its fallback port", node.id, node.type)
        return ports[-1], {}
    if str(chosen) not in ports:
        return ports[-1], {}
    return str(chosen), dict(ctx.outputs)


@dataclass
class _NodeContext:
    """What a contributed node's planner is handed. Deliberately small: a session
    for its own reads, the node it is, and the packet — not the whole engine."""

    session: AsyncSession
    node: Node
    packet: Packet
    #: Who the automation runs as. A contributed node reads THROUGH this, so its
    #: prompt can only contain what that identity could already see, and an
    #: action applies with exactly that identity's rights.
    #:
    #: That bounds the INPUT and says nothing about the output, which matters
    #: since spec 119: this actor is the automation's, usually wider than the
    #: submitter's, and a finding is shown to whoever submitted — a portal
    #: visitor included. A node that reads widely and then writes what it read
    #: into a finding has crossed a boundary the identity alone does not close.
    actor: User
    #: The ids of the node's DECLARED subject this invocation is for (RADD-923):
    #: one id per call at item arity, the whole set at set arity. A node acting
    #: on milestones gets milestone ids and never sees the item machinery.
    subject_ids: tuple[uuid.UUID, ...] = ()
    #: Where `add_finding` writes — the walk's report list (spec 119). None on
    #: any walk that is not collecting, which is what makes the seam a no-op
    #: rather than a second thing every contributed node has to check.
    findings: list[Finding] | None = None
    #: `time.monotonic()` past which an expensive check should stop asking.
    deadline: float | None = None
    #: Where `set_output` writes (spec 120). A plain dict on the context rather
    #: than a return value, because a node that ROUTES already returns its port
    #: — asking it to return a pair as well would make every existing planner a
    #: signature break, and `add_finding` had already established the seam shape.
    outputs: dict[str, str] = field(default_factory=dict)

    def set_output(self, name: str, value: Any) -> None:
        """A contributed node's seam for saying what it PRODUCED (spec 120).

        The executor files these under the node's name, so a downstream action
        can write `{{triage.priority}}`. A METHOD, like `add_finding`, so a node
        never constructs the vocabulary: it says what it produced and the
        executor decides whether the invocation is one that can be addressed at
        all (a per-item run is not — see `_partition_registered`).

        Names outside the identifier rule are DROPPED rather than stored: a
        value nothing could ever reference is not a value, and storing it would
        put an unreachable row in the dry-run report.
        """
        key = str(name or "").strip()
        if not valid_output_name(key):
            logger.warning(
                "automations: node %s tried to produce %r, which is not a usable output name",
                self.node.id, name,
            )
            return
        self.outputs[key] = "" if value is None else str(value)

    def out_of_time(self) -> bool:
        """Whether the walk's wall-clock budget is spent.

        A node that costs a network round trip asks this before spending one.
        The executor cannot decide on its behalf, because what a node does when
        it runs out of time is the node's own policy — `ai.validate` takes its
        `on_unavailable` path, which an admin configured precisely for "the
        check could not run".
        """
        return self.deadline is not None and monotonic() >= self.deadline

    def add_finding(self, message: str, field: str = "") -> None:
        """A contributed node's seam for saying what is wrong with the draft.

        A METHOD rather than a mutable list a node appends dicts to, because the
        `Finding` type belongs to `automations` and the nodes contributing
        findings live in other modules (`ai.validate` is the first). A node calls
        this; it never constructs the vocabulary. Blank messages are dropped —
        an empty finding fails a submission while explaining nothing, which is
        the worst possible refusal.
        """
        text = str(message or "").strip()
        if self.findings is None or not text:
            return
        self.findings.append(Finding(node_id=self.node.id, message=text, field=str(field or "")))


def _context(
    report: RunReport,
    *,
    session: AsyncSession,
    node: Node,
    packet: Packet,
    actor: User,
    subject_ids: tuple[uuid.UUID, ...] = (),
) -> _NodeContext:
    """The one place a contributed node's context is built.

    A factory rather than four call sites repeating the same arguments: the
    findings gate and the deadline are properties of the WALK, and a site that
    forgot either would give one node a different contract from its neighbours.
    """
    return _NodeContext(
        session=session,
        node=node,
        packet=packet,
        actor=actor,
        subject_ids=subject_ids,
        findings=report.findings if report.collecting else None,
        deadline=report.deadline,
    )


async def _actor_for(session: AsyncSession, node: Node, default: User) -> User:
    """Who this action runs as.

    `act_as` on the node names a user by email; absent, the automation's author
    (passed in as `default`). Falls back to the default when the named account no
    longer resolves — an automation must not stop working because someone left,
    and it must not silently escalate either, which is why it falls back to the
    author rather than to the system actor.
    """
    email = str(node.params.get("act_as") or "").strip()
    if not email:
        return default
    found = (
        await session.execute(select(User).where(User.email == email, User.active.is_(True)))
    ).scalar_one_or_none()
    if found is None:
        logger.warning(
            "automations: node %s acts as %r, which no longer resolves — using the author",
            node.id, email,
        )
        return default
    return found


async def _run_action(
    session: AsyncSession,
    *,
    node: Node,
    packet: Packet,
    system_user: User,
    automation_name: str,
    budget: RunBudget,
    apply: bool,
    report: RunReport,
) -> tuple[list[uuid.UUID], dict[str, str]]:
    """Fire the action once, or once per item, per its arity.

    Returns the ids of anything it CREATED (for the `created` port) and the
    named values it PRODUCED (spec 120, for the variable bag). Producing is a
    SET-arity property: a per-item run makes one value per item, and the bag has
    one slot per node, so those are deliberately not collected — see `_stamp`.
    """
    from .types import ActionType

    # A CONTRIBUTED action first (RADD-923). Until now a plugin could declare an
    # action node and the executor would drop it — `ActionType(action_name)`
    # raised, it logged "unknown action type", and the node silently never ran.
    # So a plugin could say "when my deployment finishes" and "if the AI says
    # it's risky", but never "…then do my thing".
    spec = spec_for(node)
    if spec is not None and spec.plan is not None:
        produced = await _run_contributed_action(
            session,
            node=node,
            spec=spec,
            packet=packet,
            system_user=system_user,
            automation_name=automation_name,
            budget=budget,
            apply=apply,
            report=report,
        )
        return [], produced

    # `validation.fail` (spec 119): reaching it IS the check failing. It writes
    # nothing and takes no budget beyond the node it already spent, so it runs
    # identically on a dry run and a live one — there is no applying half to
    # switch off, which is the whole reason a finding is not an action.
    if node.type == TYPE_VALIDATION_FAIL:
        if not report.collecting:
            # Not a validation walk: nobody is asking, so nothing is recorded.
            # The node still passes its packet through (below), because a graph
            # that also fires on an event must not lose its downstream branch
            # just because one node in it has nothing to say here.
            return [], {}
        if packet.is_empty:
            # THE APPLICABILITY RULE, and it is not obvious. A universal action
            # at SET arity fires on an empty packet on purpose ("nothing matched
            # — tell me"), and inheriting that here made `trigger → filter →
            # matched → check` report its finding about a draft the filter had
            # just EXCLUDED. Conditional checks are the whole reason the trigger
            # takes no condition params, so an empty packet means this branch
            # does not apply to this draft, and the check stays quiet.
            return [], {}
        message = str(node.params.get("message") or "").strip()
        report.findings.append(
            Finding(
                node_id=node.id,
                # The message is required on write. A row edited around the API
                # still has to say SOMETHING: a refusal that explains nothing is
                # worse than one that admits the check is misconfigured.
                message=message or UNSPOKEN_FINDING,
                field=str(node.params.get("field") or ""),
            )
        )
        return [], {}

    action_name = node.type.removeprefix(ACTION_TYPE_PREFIX)
    try:
        ActionType(action_name)
    except ValueError:
        # An unknown action type halts THIS node loudly rather than being skipped
        # in silence — most often a plugin that has been uninstalled.
        logger.error("automations: %s: unknown action node type %r", automation_name, node.type)
        budget.dropped.append(f"node {node.id!r} — unknown action type {node.type!r}")
        return [], {}

    from .planning import load_item_facts

    stored = {"type": action_name, "params": node.params}
    actor = await _actor_for(session, node, system_user)
    loaded = await _load(session, packet.item_ids)
    # What `{{item.*}}` can say (RADD-1265), fetched once for the whole node
    # rather than per invocation: a per-item run over 200 issues is 200
    # renders, not 800 queries.
    facts = await load_item_facts(session, loaded)

    if arity_of(node) is NodeArity.SET:
        # ONE run for the whole packet — a digest webhook, a single triage
        # ticket. It still fires on an empty packet: "nothing matched today, tell
        # me" is a real automation, and it is why empty sets propagate at all.
        #
        # A packet holding exactly ONE item passes it as the target, which is
        # what makes `{{item.key}}` resolve on an event-triggered run. With
        # several there is no single item the run is "about" and the item tokens
        # are blank by construction — `{{items.keys}}` is the set-shaped answer.
        item, project = loaded[0] if len(loaded) == 1 else (None, None)
        outcome = await _one(
            session, node, stored, item, project, actor, packet, loaded,
            automation_name, apply, report, facts,
        )
        made = [outcome.created_id] if outcome.created_id is not None else []
        return made, outcome.produced

    if packet.is_empty:
        logger.info(
            "automations: %s: per-item action %s skipped — nothing reached node %s",
            automation_name, action_name, node.id,
        )
        return [], {}

    # Metered whatever the action is. Before RADD-918 only the ten item-mutating
    # actions consumed budget, because they were the only ones that could fan
    # out; a per-item webhook would otherwise be the one unbounded thing in the
    # engine.
    allowed = budget.take_item_actions(node, len(loaded))
    created: list[uuid.UUID] = []
    for item, project in loaded[:allowed]:
        outcome = await _one(
            session, node, stored, item, project, actor, packet, [(item, project)],
            automation_name, apply, report, facts,
        )
        if outcome.created_id is not None:
            created.append(outcome.created_id)
    # No variables: N invocations produced N answers and the bag has one slot.
    return created, {}


async def _run_contributed_action(
    session: AsyncSession,
    *,
    node: Node,
    spec,
    packet: Packet,
    system_user: User,
    automation_name: str,
    budget: RunBudget,
    apply: bool,
    report: RunReport,
) -> dict[str, str]:
    """Run a plugin's action node (RADD-923).

    Contained by construction, and every clause here is one of the containments:

    * it acts on the ids of its DECLARED subject, so a milestone action never has
      to know how an item-shaped packet is assembled;
    * `plan` runs on every walk including a dry run, which is what makes the
      report free and identical to the real thing;
    * `apply` runs inside the executor's SAVEPOINT, inside its `RunBudget`, and
      inside `events.automated()` — so a plugin action cannot spin the engine,
      cannot escape the budget, and cannot take the branch down when it raises;
    * it runs as the `act_as` actor, so it cannot escalate past whoever the
      automation is allowed to act as.
    """
    ids = packet.ids_of(spec.subject or graph.ITEM_SUBJECT)
    actor = await _actor_for(session, node, system_user)
    per_item = arity_of(node) is NodeArity.ITEM

    if per_item and not ids:
        logger.info(
            "automations: %s: %s skipped — no %s reached node %s",
            automation_name, node.type, spec.subject, node.id,
        )
        return {}

    batches: list[tuple[uuid.UUID, ...]] = (
        [(one,) for one in ids[: budget.take_item_actions(node, len(ids))]]
        if per_item
        else [tuple(ids)]
    )
    produced: dict[str, str] = {}
    for batch in batches:
        try:
            async with session.begin_nested():
                ctx = _context(
                    report, session=session, node=node, packet=packet, actor=actor,
                    subject_ids=batch,
                )
                plan = await spec.plan(ctx)
                resolves = bool(getattr(plan, "resolves", plan is not None))
                report.plans.append(
                    PlannedAction(
                        node_id=node.id,
                        action_type=node.type,
                        params=dict(node.params),
                        item_id=batch[0] if batch else None,
                        resolves=resolves,
                        detail=str(getattr(plan, "detail", plan or "")),
                    )
                )
                if apply and resolves and spec.apply is not None:
                    # THE LOOP GUARD covers whatever the plugin emits, exactly as
                    # it covers a built-in action.
                    with events.automated():
                        await spec.apply(ctx, plan)
                # Only a SET-arity run makes an addressable value — one batch,
                # one answer. Per item there are N, and the bag has one slot.
                if not per_item:
                    produced = dict(ctx.outputs)
        except Exception:
            logger.exception(
                "automations: contributed action %s of %s failed", node.id, automation_name
            )
    return produced


async def _one(
    session: AsyncSession,
    node: Node,
    stored: dict,
    item: WorkItem | None,
    project: Project | None,
    actor: User,
    packet: Packet,
    scope: list[tuple[WorkItem, Project | None]],
    automation_name: str,
    apply: bool,
    report: RunReport,
    facts: dict[uuid.UUID, dict[str, Any]] | None = None,
) -> "_Outcome":
    """Plan one action, then apply it — inside a SAVEPOINT so a failure rolls back
    only itself. The plan is recorded either way, which is what lets a dry run
    report exactly what a real run would have done.

    `scope` is the items this ONE invocation speaks for: the whole packet at set
    arity, the single item at item arity. It is what the set-shaped tokens and
    the webhook's `items[]` render from, so a per-item webhook describes its own
    item and a digest describes all of them, with no branch in the planner.

    Returns what the invocation made: the id of anything created (for the
    `created` port) and the named values it produced (spec 120).
    """
    from .engine import _apply_plan
    from .planning import _plan, items_ctx

    try:
        async with session.begin_nested():
            plan = await _plan(
                session, stored, item, project, actor,
                facts=packet.facts, rule_name=automation_name,
                items=items_ctx(scope, facts),
                variables=packet.vars,
                item_facts=(facts or {}).get(item.id) if item is not None else None,
            )
            report.plans.append(
                PlannedAction(
                    node_id=node.id,
                    action_type=str(stored["type"]),
                    params=dict(stored.get("params") or {}),
                    item_id=item.id if item is not None else None,
                    resolves=plan.kind is not PlanKind.SKIP,
                    detail=plan.detail,
                    resolved=dict(plan.resolved),
                )
            )
            if plan.kind is PlanKind.SKIP:
                logger.info("automations: %s %s", automation_name, plan.detail)
                return _Outcome()
            if not apply:
                return _Outcome()
            # THE LOOP GUARD. Every event this mutation emits is marked
            # automation-caused, whoever it ran as — which is the whole
            # reason `act as` is safe: identity moved, causation did not.
            with events.automated():
                made = await _apply_plan(session, plan, item, actor, rule_name=automation_name)
            return _created_outcome(made)
    # EVERY refusal is caught OUTSIDE the savepoint, and that placement is the
    # whole correctness of it. `items.update_item` mutates the row and THEN asks
    # `workflow.check_transition`; catching the refusal inside the `begin_nested`
    # block lets its `__aexit__` COMMIT, which flushes the state change the guard
    # had just refused — and because the check raises before `_finish`, no
    # `item.updated` event is emitted either, so the move lands with no history,
    # no notification and no reindex while the run report calls it a skip. Out
    # here the savepoint has already rolled back; `report.plans` is a plain
    # Python list and survives, so the entry can be rewritten in place.
    except TransitionError as refusal:
        # A WORKFLOW GUARD said no. Not an engine failure and not a bug: the
        # project's transition rules apply to automations too, deliberately.
        # What was wrong is that this landed in the generic handler below —
        # logged as a crash, and reported by the dry run as an action that
        # "would apply" and never could.
        _record_refusal(
            report,
            f"refused by the workflow: {'; '.join(refusal.errors) or refusal} "
            f"(from {refusal.from_state} to {refusal.to_state})",
        )
        logger.info(
            "automations: %s node %s refused by the workflow: %s",
            automation_name, node.id, refusal,
        )
    except FieldValidationError as invalid:
        # The FIELD REGISTRY said no — most often a rendered value that is not
        # one of a select's options, which is exactly what a tokenized custom
        # field invites. Same treatment as a guard refusal: the validator's own
        # sentences, recorded against the action that would have written them,
        # rather than a stack trace and a report that still says "would apply".
        _record_refusal(report, f"refused: {'; '.join(invalid.errors) or invalid}")
        logger.info(
            "automations: %s node %s refused by field validation: %s",
            automation_name, node.id, invalid,
        )
    except Exception:
        logger.exception(
            "automations: node %s of %s failed (item %s)",
            node.id, automation_name, item.id if item is not None else "—",
        )
    return _Outcome()


def _record_refusal(report: RunReport, reason: str) -> None:
    """Turn the plan just recorded into the skip a validator made it.

    The plan is appended BEFORE the apply — that is what makes a dry run free —
    so by the time anything refuses, the report already says the action would
    apply. Rewriting the last entry keeps one record per invocation instead of
    two that contradict each other.
    """
    if not report.plans:  # pragma: no cover — an apply always follows a plan
        return
    planned = report.plans[-1]
    report.plans[-1] = replace(
        planned, resolves=False, refused=True, detail=f"{planned.detail} — {reason}"
    )


@dataclass(frozen=True)
class _Outcome:
    """What one action invocation left behind: the id of anything it CREATED and
    the values it made addressable (spec 120)."""

    created_id: uuid.UUID | None = None
    produced: dict[str, str] = field(default_factory=dict)


def _created_outcome(made: Any) -> _Outcome:
    """The `create_item` outcome, read off the item the applier returned.

    Key and URL rather than the id alone, because "file a follow-up and then say
    which one" is the whole reason this is addressable — and nobody recognises a
    uuid in a comment. The URL is built from `app_base_url` the same way every
    notification builds one, so a link in an automation's comment goes where a
    link in its email goes.
    """
    item_id = getattr(made, "id", None)
    if item_id is None:
        return _Outcome()
    key = str(getattr(made, "key", "") or "")
    return _Outcome(
        created_id=item_id,
        produced={
            "id": str(item_id),
            "key": key,
            "url": f"{settings.app_base_url.rstrip('/')}/issues/{key}" if key else "",
        },
    )


async def load_graph(automation) -> tuple[list[Node], list[Edge], list[Node]]:
    """Parse and re-validate a stored graph, returning its TRIGGERS. Validation
    runs on write too; doing it again here is deliberate, so a row edited around
    the API cannot wedge the consumer."""
    nodes, edges = graph.parse(automation.nodes or [], automation.edges or [])
    triggers = graph.validate(nodes, edges, ports_of)
    return nodes, edges, triggers
