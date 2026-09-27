"""Walking an automation graph (spec 116): what each node MEANS. `graph.py`
decides legality and order; this module has the I/O.

* Budget: `RunBudget` caps node runs and item-actions and RECORDS what it
  dropped — a silent cap makes "did less" look like "had less to do".
* Best-effort: each action runs in a SAVEPOINT, so one failure rolls back only
  itself and the walk continues.
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
from .nodes import arity_of, needs_items, output_name, ports_of, spec_for
from .graph import Edge, Node, Packet
from .templating import MissingTemplateOutput
from .types import (
    AutomationNodeKind,
    AutomationTrigger,
    NodeArity,
    NodePort,
    ValidationMode,
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


def new_budget() -> RunBudget:
    return RunBudget(
        max_nodes=settings.automation_graph_max_node_runs,
        max_item_actions=settings.automation_graph_max_item_actions,
    )


@dataclass(frozen=True)
class Finding:
    """One problem with the draft a validation walk inspects (spec 119). `field`
    names the control to fix (builtin name or `cf.<key>`), empty for the whole
    submission, validated loosely so a deleted field degrades to plain advice.
    `mode` is set by the verdict node that spoke (RADD-1329): one draft may be
    both blocked and warned."""

    node_id: str
    message: str
    mode: str  # a `ValidationMode` value
    field: str = ""


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
    #: True when the action RAISED (or its type is unknown): the one outcome that
    #: halts the branch for its item (RADD-1450). A skip is "nothing to do
    #: here" and a refusal is "the project said no"; neither is an error, and
    #: the items behind them still reach the next node.
    failed: bool = False


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
    #: What check nodes published, by node id (RADD-1329); read by verdict nodes.
    published: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    #: True when the walk entered through a `validate` trigger (manual runs and
    #: previews of one included); elsewhere `add_finding` is a no-op.
    collecting: bool = False
    draft_id: uuid.UUID | None = None
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
        draft_id=initial.item_ids[0] if len(initial.item_ids) == 1 else None,
        deadline=deadline,
    )
    order = graph.topological_order(nodes, edges)
    inbound = graph.inbound(edges)
    #: Where each node sits in the run. Fan-in merges its feeders in THIS order
    #: (spec 120) rather than in the order the edges happen to be stored, so
    #: "the later producer's variables win" means the one that actually ran
    #: second — and so two saves of the same graph cannot merge differently.
    rank = {node.id: index for index, node in enumerate(order)}

    #: (node id, port) -> what it emitted. A MISSING port = branch not taken (a gate
    #: emits only its choice); an EMPTY packet = ran and matched nothing (a filter
    #: emits both). Branch semantics depend on that difference.
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

    report.dropped.extend(budget.dropped)
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
    spec = spec_for(node)
    if not apply and spec is not None and not spec.preview_safe:
        if report.collecting:
            raise ValueError(f"{spec.label} cannot execute during submission validation")
        report.dropped.append(f"{node.id}: {spec.label} was not executed in preview; its downstream branches cannot be simulated.")
        return {}
    if node.kind is AutomationNodeKind.TRIGGER:
        return {NodePort.OUT.value: packet}

    if node.kind is AutomationNodeKind.SOURCE:
        return {
            NodePort.OUT.value: await _run_source(
                session, node, packet, system_user, automation_name, report
            )
        }

    if node.kind in (AutomationNodeKind.GATE, AutomationNodeKind.FILTER):
        return await _run_router(session, node, packet, system_user, report)

    planned_before = len(report.plans)
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
    # Only a FAILED invocation takes its item out of the packet (RADD-1450): a
    # skip ("no assignee to watch") or a refusal leaves the item as it was, and
    # the next node still has something true to act on. A set-arity failure has
    # no single item to drop, so the whole branch stops.
    invocations = report.plans[planned_before:]
    failures = [p for p in invocations if p.failed]
    if any(p.item_id is None for p in failures):
        return {}
    if failures:
        failed_ids = {p.item_id for p in failures}
        subject = (spec.subject if spec else "") or graph.ITEM_SUBJECT
        packet = packet.with_subject(subject, [i for i in packet.ids_of(subject) if i not in failed_ids])
        if not packet.ids_of(subject):
            return {}
    if not apply and spec is not None and (spec.outputs_at(node.params) or NodePort.CREATED.value in ports_of(node)) and any(p.resolves for p in invocations):
        report.dropped.append(f"{node.id}: action outputs and created objects are unavailable in preview; dependent branches are not simulated.")
        return {}
    passthrough = _stamp(node, packet, produced, report)
    outputs = {NodePort.OUT.value: passthrough}
    if NodePort.CREATED.value in ports_of(node):
        # What it MADE, per subject (RADD-1322): a plugin action that creates
        # milestones feeds milestones downstream exactly as `create_item`
        # feeds issues. Nothing made is an empty packet, not the input.
        made = passthrough.with_items(())
        for subject, ids in created.items():
            made = made.with_subject(subject, ids)
        outputs[NodePort.CREATED.value] = made
    return outputs


def _stamp(
    node: Node, packet: Packet, produced: dict[str, str], report: RunReport
) -> Packet:
    """The packet a producing node emits: its input plus what it produced, under
    the node's NAME, on every port it emits (spec 120). Recorded in the report
    either way."""
    if not produced:
        return packet
    report.produced[node.id] = dict(produced)
    return packet.with_vars(output_name(node), produced)


# --- sources: the nodes that PRODUCE a subject's ids ---------------------------


async def _run_source(
    session: AsyncSession,
    node: Node,
    packet: Packet,
    actor: User,
    automation_name: str,
    report: RunReport,
) -> Packet:
    """Ask a source for the ids it produces (RADD-1322: the search node is one
    spec among any a plugin registers). The packet leaves carrying those ids as
    the source's declared SUBJECT; a failure produces nothing rather than
    taking the automation down — the report shows a source that found zero."""
    spec = spec_for(node)
    subject = (spec.subject if spec else "") or graph.ITEM_SUBJECT
    if spec is None or spec.plan is None:
        logger.error("automations: %s: unknown source node type %r", automation_name, node.type)
        return packet.with_subject(subject, ())
    ctx = _context(
        report, session=session, node=node, packet=packet, actor=actor, automation_name=automation_name
    )
    try:
        found = await spec.plan(ctx)
    except Exception:
        logger.exception("automations: %s: source %s failed", automation_name, node.id)
        return packet.with_subject(subject, ())
    return packet.with_subject(subject, tuple(found or ()))


# --- routers: gates and filters, which differ only in how they read the packet ---


async def _run_router(
    session: AsyncSession,
    node: Node,
    packet: Packet,
    actor: User,
    report: RunReport,
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

    spec = spec_for(node)
    subject = (spec.subject if spec else "") or graph.ITEM_SUBJECT
    assigned = await _partition(session, node, packet, actor, report)
    ids = packet.ids_of(subject)
    return {
        port: packet.with_subject(subject, [i for i in ids if assigned.get(i) == port])
        for port in ports
    }


async def _route(
    session: AsyncSession, node: Node, packet: Packet, actor: User, report: RunReport
) -> tuple[str, dict[str, str]]:
    """Ask a gate which port the packet leaves by, plus what it produced. Any
    failure takes the spec's LAST port (every router's fallback) and produces
    nothing, so downstream tokens miss rather than reading stale values."""
    spec = spec_for(node)
    if spec is None or spec.plan is None:
        # A router this build does not know — most often an uninstalled plugin's.
        logger.error("automations: node %s: unknown router type %r", node.id, node.type)
        ports = ports_of(node)
        return (ports[-1] if ports else NodePort.FALSE.value), {}
    ports = spec.ports_at(node.params)
    if not ports:
        return "", {}
    if packet.is_empty and needs_items(node):
        # The node said it has nothing to say about no items.
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


async def _partition(
    session: AsyncSession, node: Node, packet: Packet, actor: User, report: RunReport
) -> dict[uuid.UUID, str]:
    """subject id -> the port it leaves by, for an ITEM-arity router, over its
    declared SUBJECT (RADD-1322). `plan_items` when the node has one (the executor
    shares one session, so only the node may batch or parallelise), else `plan`
    once per single-item packet."""
    spec = spec_for(node)
    if spec is None:
        logger.error("automations: node %s (%s) cannot run per item", node.id, node.type)
        return {}
    if not packet.ids_of(spec.subject or graph.ITEM_SUBJECT):
        return {}
    ports = spec.ports_at(node.params)
    if not ports:
        return {}
    fallback = ports[-1]
    subject = spec.subject or graph.ITEM_SUBJECT
    ids = packet.ids_of(subject)

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
            return {item_id: fallback for item_id in ids}
        return {
            item_id: (str(answers.get(item_id)) if str(answers.get(item_id)) in ports else fallback)
            for item_id in ids
        }

    if spec.plan is None:
        return {item_id: fallback for item_id in ids}
    # The produced values are DROPPED at item arity, deliberately (spec 120).
    # Each item has its own answer, and the bag has one slot per node name — so
    # `{{classify.answer}}` could only ever name one of them, silently. A token
    # that misses is recorded and skips the action; a token that resolves to
    # some other item's answer is a wrong write nobody would notice.
    return {
        item_id: (
            await _route(session, node, packet.with_subject(subject, (item_id,)), actor, report)
        )[0]
        for item_id in ids
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


@dataclass
class _NodeContext:
    """What a contributed node's planner is handed. Deliberately small: a session
    for its own reads, the node it is, and the packet — not the whole engine."""

    session: AsyncSession
    node: Node
    packet: Packet
    #: Who the automation runs as; nodes read THROUGH it. It bounds the input, not
    #: the output: a finding is shown to the submitter (spec 119's leak rule).
    actor: User
    #: The ids of the node's DECLARED subject this invocation is for (RADD-923):
    #: one id per call at item arity, the whole set at set arity. A node acting
    #: on milestones gets milestone ids and never sees the item machinery.
    subject_ids: tuple[uuid.UUID, ...] = ()
    #: Where `add_finding` writes — the walk's report list (spec 119). None on
    #: any walk that is not collecting, which is what makes the seam a no-op
    #: rather than a second thing every contributed node has to check.
    findings: list[Finding] | None = None
    draft_id: uuid.UUID | None = None
    resolved: dict[str, str] = field(default_factory=dict)
    #: `time.monotonic()` past which an expensive check should stop asking.
    deadline: float | None = None
    #: Where `set_output` writes (spec 120). A plain dict on the context rather
    #: than a return value, because a node that ROUTES already returns its port
    #: — asking it to return a pair as well would make every existing planner a
    #: signature break, and `add_finding` had already established the seam shape.
    outputs: dict[str, str] = field(default_factory=dict)
    #: The automation's name, for a node's log lines and labels (RADD-1322).
    automation_name: str = ""
    #: What CHECK nodes published this walk, by node id (RADD-1329) — the walk's
    #: shared store, so a verdict node downstream can relay a check's findings.
    published: dict[str, list[dict[str, Any]]] | None = None
    #: A memo shared by every invocation of ONE node in one walk (RADD-1322) —
    #: a per-item action over 200 issues loads their facts once, not 200 times.
    cache: dict[str, Any] = field(default_factory=dict)
    #: What the node MADE, per subject, for the `created` port (RADD-1322).
    created: dict[str, list[uuid.UUID]] = field(default_factory=dict)

    def _item_ids(self) -> tuple[uuid.UUID, ...]:
        """The items this invocation speaks for: the one it was handed at
        per-item arity, else the packet's."""
        if self.node.kind is AutomationNodeKind.ACTION and arity_of(self.node) is NodeArity.ITEM:
            return self.subject_ids
        return self.packet.item_ids

    async def render(self, text: Any, *, line: bool = False) -> str:
        """Substitute `{{tokens}}` in a contributed node's text exactly as a
        built-in action's are (RADD-1324): the event's roots, every registered
        provider's (`page`, `comment`, a plugin's), the variable bag,
        `{{item.*}}` when the invocation speaks for exactly one item, and the
        set tokens `{{items.*}}` over everything it speaks for (RADD-1387 — a
        contributed send_email's digest body needs `{{items.list}}`).
        `line=True` collapses whitespace — for a value that NAMES something or
        becomes a header, never for a body. Missing named outputs refuse
        execution; absent optional event fields remain verbatim."""
        from .planning import _item_ctx, items_ctx, load_item_facts
        from .templating import TOKEN_RE, Renderer

        ids = self._item_ids()
        wants_set = any(match.group(1).startswith("items.") for match in TOKEN_RE.finditer(str(text)))
        item_ctx, items = None, [] if wants_set else None
        if ids and (len(ids) == 1 or wants_set):
            # Memoised per node: a subject, a body and a recipient are three
            # renders over the same items, not three loads.
            memo = self.cache.setdefault("render.loaded", {})
            if ids not in memo:
                loaded = await _load(self.session, ids)
                memo[ids] = (loaded, await load_item_facts(self.session, loaded))
            loaded, facts = memo[ids]
            if len(loaded) == 1:
                item, project = loaded[0]
                item_ctx = _item_ctx(item, project, facts.get(item.id))
            if wants_set:
                items = items_ctx(loaded, facts)
        renderer = Renderer(self.packet.facts, item_ctx, items, self.packet.vars)
        result = renderer.line(text) if line else renderer(text)
        self.resolved.update(renderer.resolved)
        if renderer.misses:
            raise MissingTemplateOutput("; ".join(renderer.misses))
        return result

    async def target_item(self) -> WorkItem | None:
        """The ONE item this invocation is about, or None when it speaks for
        several or none — the item a role like `reporter` resolves on."""
        ids = self._item_ids()
        return await self.session.get(WorkItem, ids[0]) if len(ids) == 1 else None

    async def person(self, value: Any):
        """A PERSON param read as the built-ins read one (RADD-1387): a role
        (`reporter`/`assignee`) on the target item, else an email — rendered
        first, so `{{triage.owner}}` works. Returns `roles.Person` or None, and
        the node words its own skip, so a plugin's action (participants'
        Add participant) needs no import of this module."""
        from .roles import is_role, resolve_person

        raw = str(value or "")
        named = raw if is_role(raw) else await self.render(raw, line=True)
        return await resolve_person(self.session, named, await self.target_item())

    async def render_draft(self, text: str) -> str:
        """Only the original draft's title may cross the submitter boundary.

        Relationship names and administrative fields are deliberately excluded:
        the automation actor's access is not the submitter's access.
        """
        from .templating import TOKEN_RE

        draft = await self.session.get(WorkItem, self.draft_id) if self.draft_id else None
        values = {"item.title": draft.title if draft is not None else ""}
        return TOKEN_RE.sub(lambda match: values.get(match.group(1), ""), text)

    def add_created(self, subject: str, entity_id: uuid.UUID) -> None:
        """Say this invocation CREATED a row, so the node's `created` port carries
        it downstream — `create_item`'s follow-up issue, a plugin's new row. A
        method for the reason `set_output` is one: the node says what it made,
        and the executor decides where it goes."""
        self.created.setdefault(str(subject), []).append(entity_id)

    def set_output(self, name: str, value: Any) -> None:
        """File a produced value under this node's name (spec 120) for
        `{{name.field}}` downstream. Names that are not legal identifiers are
        dropped — nothing could reference them."""
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
        it runs out of time is the node's own policy — `ai.validate` leaves by
        its "can't check" port, whose meaning is whatever the graph wired there.
        """
        return self.deadline is not None and monotonic() >= self.deadline

    def publish_findings(self, found: list[dict[str, Any]]) -> None:
        """A CHECK node's seam for saying what it found WITHOUT deciding what
        happens to the submission (RADD-1329): the findings are kept under the
        node's id for a downstream "Block submission" / "Warn submitter" node to
        relay. Each is `{message, field, blocking}`. Kept on every walk — a dry
        run reports them — and read only by verdict nodes."""
        if self.published is not None:
            entries = [dict(entry) for entry in found]
            if self.findings is not None and self.packet.item_ids != (self.draft_id,):
                # A check over search results cannot quote those records to a
                # submitter. Preserve its verdict, but not privileged content.
                entries = [{"message": "This submission did not pass a related-record check.",
                            "field": "", "blocking": entry.get("blocking", True)} for entry in entries]
            self.published[self.node.id] = entries

    def published_by(self, node_id: str) -> list[dict[str, Any]]:
        """What an upstream check published, for a verdict node relaying it."""
        return list((self.published or {}).get(str(node_id), []))

    def add_finding(
        self, message: str, field: str = "", *, blocking: bool = False, source: str = ""
    ) -> None:
        """A node's seam for a finding on the draft; blank messages are dropped
        (an empty finding refuses while explaining nothing)."""
        text = str(message or "").strip()
        if self.findings is None or not text:
            return
        mode = (ValidationMode.REQUIRED if blocking else ValidationMode.ADVISORY).value
        # A RELAYED finding names the check that produced it (RADD-1329), so the
        # report still says which check spoke — the verdict node only decided.
        self.findings.append(
            Finding(node_id=source or self.node.id, message=text, field=str(field or ""), mode=mode)
        )


def _context(
    report: RunReport,
    *,
    session: AsyncSession,
    node: Node,
    packet: Packet,
    actor: User,
    subject_ids: tuple[uuid.UUID, ...] = (),
    automation_name: str = "",
    cache: dict[str, Any] | None = None,
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
        draft_id=report.draft_id,
        deadline=report.deadline,
        automation_name=automation_name,
        cache=cache if cache is not None else {},
        published=report.published,
    )


async def _actor_for(session: AsyncSession, node: Node, default: User) -> User:
    """Resolve the configured account; never substitute a more privileged user."""
    email = str(node.params.get("act_as") or "").strip()
    account_id = node.params.get("act_as_id")
    if not email and not account_id:
        return default
    if account_id:
        found = await session.get(User, uuid.UUID(str(account_id)))
    else:
        found = await session.scalar(select(User).where(User.email == email))
    if found is None or not found.active:
        raise RuntimeError(f"Execution account {email or account_id!r} is unavailable; choose an active account")
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
) -> tuple[dict[str, list[uuid.UUID]], dict[str, str]]:
    """Fire an action once, or once per subject id, per its arity — one path for
    every action. It acts on its DECLARED subject's ids; `plan` runs on every
    walk (so the dry run is free); `apply` runs inside a savepoint, the budget
    and `events.automated()`, as the `act_as` actor (else the author).

    Returns what it CREATED per subject (the `created` port) and, at SET arity,
    the values it PRODUCED (spec 120).
    """
    spec = spec_for(node)
    if spec is None or spec.plan is None:
        # An unknown action type halts THIS node loudly rather than being skipped
        # in silence — most often a plugin that has been uninstalled.
        logger.error("automations: %s: unknown action node type %r", automation_name, node.type)
        report.plans.append(_planned(node, (), resolves=False, failed=True,
            detail=f"node {node.id!r} — unknown action type {node.type!r}"))
        return {}, {}

    ids = packet.ids_of(spec.subject or graph.ITEM_SUBJECT)
    per_item = arity_of(node) is NodeArity.ITEM
    if per_item and not ids:
        logger.info(
            "automations: %s: %s skipped — no %s reached node %s",
            automation_name, node.type, spec.subject, node.id,
        )
        return {}, {}

    # Metered whatever the action is: a per-item webhook would otherwise be the
    # one unbounded thing in the engine (RADD-918).
    batches: list[tuple[uuid.UUID, ...]] = (
        [(one,) for one in ids[: budget.take_item_actions(node, len(ids))]]
        if per_item
        else [tuple(ids)]
    )
    cache: dict[str, Any] = {}
    created: dict[str, list[uuid.UUID]] = {}
    produced: dict[str, str] = {}
    for batch in batches:
        recorded = len(report.plans)
        ctx = _context(
            report, session=session, node=node, packet=packet, actor=system_user,
            subject_ids=batch, automation_name=automation_name, cache=cache,
        )
        try:
            ctx.actor = await _actor_for(session, node, system_user)
            async with session.begin_nested():
                plan = await spec.plan(ctx)
                if plan is None:
                    # Nothing to put in the report — a check that recorded a
                    # finding, or had nothing to say on this walk.
                    continue
                resolves = bool(getattr(plan, "resolves", True))
                report.plans.append(
                    _planned(
                        node, batch,
                        resolves=resolves,
                        detail=str(getattr(plan, "detail", plan)),
                        resolved={**ctx.resolved, **dict(getattr(plan, "resolved", None) or {})},
                    )
                )
                if not resolves:
                    logger.info("automations: %s %s", automation_name, getattr(plan, "detail", plan))
                if apply and resolves and spec.apply is not None:
                    # THE LOOP GUARD. Every event this mutation emits is marked
                    # automation-caused, whoever it ran as — which is the whole
                    # reason `act as` is safe: identity moved, causation did not.
                    with events.automated():
                        await spec.apply(ctx, plan)
            for subject, made in ctx.created.items():
                created.setdefault(subject, []).extend(made)
            if not per_item:
                produced = dict(ctx.outputs)
        # EVERY refusal is caught OUTSIDE the savepoint, and that placement is
        # the whole correctness of it. `items.update_item` mutates the row and
        # THEN asks `workflow.check_transition`; catching the refusal inside the
        # `begin_nested` block lets its `__aexit__` COMMIT, which flushes the
        # state change the guard had just refused — with no `item.updated`
        # event, no history, no notification. Out here the savepoint has already
        # rolled back; `report.plans` is a plain list and survives, so the entry
        # is rewritten in place.
        except MissingTemplateOutput as missing:
            report.plans.append(_planned(
                node, batch, resolves=False,
                detail=f"{node.type}: skipped — {missing}", resolved=dict(ctx.resolved),
            ))
        except TransitionError as refusal:
            # A WORKFLOW GUARD said no. Not an engine failure: the project's
            # transition rules apply to automations too, deliberately.
            _rewrite_last(
                report,
                f"refused by the workflow: {'; '.join(refusal.errors) or refusal} "
                f"(from {refusal.from_state} to {refusal.to_state})",
                since=recorded, refused=True,
            )
            logger.info(
                "automations: %s node %s refused by the workflow: %s",
                automation_name, node.id, refusal,
            )
        except FieldValidationError as invalid:
            # The FIELD REGISTRY said no — most often a rendered value that is
            # not one of a select's options. The validator's own sentences,
            # recorded against the action that would have written them.
            _rewrite_last(
                report, f"refused: {'; '.join(invalid.errors) or invalid}", since=recorded, refused=True
            )
            logger.info(
                "automations: %s node %s refused by field validation: %s",
                automation_name, node.id, invalid,
            )
        except Exception as exc:
            logger.exception("automations: action %s of %s failed", node.id, automation_name)
            # Said in the report, not only the log (RADD-1269): a raised action
            # must not read "resolves", or the run history calls it applied.
            if not _rewrite_last(report, f"failed: {exc}", since=recorded, failed=True):
                report.plans.append(_planned(
                    node, batch, resolves=False, failed=True,
                    detail=f"{node.type}: failed before planning — {exc}",
                ))
    return created, produced


def _planned(node: Node, batch: tuple[uuid.UUID, ...], **fields: Any) -> PlannedAction:
    """A report entry for one invocation of `node` over `batch`."""
    return PlannedAction(
        node_id=node.id, action_type=node.type, params=dict(node.params),
        item_id=batch[0] if len(batch) == 1 else None, **fields,
    )


def _rewrite_last(report: RunReport, reason: str, *, since: int, **flags: bool) -> bool:
    """Turn the plan just recorded into the skip/failure the apply ended in; False
    when nothing was recorded since `since`.

    The plan is appended BEFORE the apply (that is what makes a dry run free), so
    rewriting the last entry keeps one record per invocation instead of two that
    contradict each other.
    """
    if len(report.plans) <= since:
        return False
    planned = report.plans[-1]
    report.plans[-1] = replace(
        planned, resolves=False, detail=f"{planned.detail} — {reason}", **flags
    )
    return True


def _with_spec_kind(node: Node) -> Node:
    spec = spec_for(node)
    if spec is None or spec.kind == node.kind.value:
        return node
    logger.warning("automations: node %s stored as %s, but %s is a %s", node.id, node.kind.value, node.type, spec.kind)
    return replace(node, kind=AutomationNodeKind(spec.kind))


async def load_graph(automation) -> tuple[list[Node], list[Edge], list[Node]]:
    """Parse and re-validate a stored graph, returning its TRIGGERS. Validation
    runs on write too; doing it again here is deliberate, so a row edited around
    the API cannot wedge the consumer."""
    nodes, edges = graph.parse(automation.nodes or [], automation.edges or [])
    # RADD-1322: a node's KIND is its spec's, not whatever the row says. The
    # write path refuses a disagreement; a row edited around the API is
    # corrected here rather than dispatched as something it is not.
    nodes = [_with_spec_kind(node) for node in nodes]
    triggers = graph.validate(nodes, edges, ports_of)
    return nodes, edges, triggers
