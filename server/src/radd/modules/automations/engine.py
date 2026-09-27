"""The automation engine: an outbox consumer that walks each matching
automation's graph and applies its action nodes' plans, as the automation's
author (or a node's `act_as`; the system actor for rows with no author).

Loop guard: every applied mutation runs in `events.automated()`, so its events
carry the `automated` marker and the cause (automation, chain depth —
RADD-1315). Such an event reaches only triggers that opted in, never the
automation that caused it, never past `automation_max_chain_depth`.

Event, schedule and manual runs all call `run_graph`, so branching lives once
in `executor.walk`; `preview` is the same walk with `apply=False`.
"""

import hashlib
import hmac
import json
import logging
from dataclasses import replace
from functools import partial
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.auth.models import User
from radd.modules.items.enums import ItemEntity
from radd.modules.comments import service as comments
from radd.modules.events import service as events
from radd.modules.events.service import Event
from radd.modules.items import service as items
from radd.modules.items.models import WorkItem
from radd.modules.items import bulk
from radd.modules.items.schemas import ItemBulkMove, ItemLinkCreate, ItemRead
from radd.modules.notify import service as notify_service
from radd.modules.projects.models import Project
from radd.modules.notify.types import NotificationType
from radd.clock import utcnow

from . import catalog, conditions, executor, graph, round_robin, runs, service
from .graph import GraphError, Packet
from .models import Automation
from .planning import (
    _Plan,
    _event_facts,
    _is_clear as _is_clear,
    _manual_facts as _manual_facts,
    _plan as _plan,
    _resolve_target_item,
    condition_matches as condition_matches,
    is_automation_caused as is_automation_caused,
    should_process as should_process,
)
from .nodes import output_name, ports_of
from .schemas import (
    ActionPreview,
    NodeResult,
    PortResult,
    ProducedVar,
    RuleTestResult,
    TestFinding,
)
from .types import (
    CONSUMER_NAME,
    SYSTEM_ACTOR_EMAIL,
    SYSTEM_ACTOR_ID,
    SYSTEM_ACTOR_NAME,
    AutomationEntity,
    AutomationEvent,
    AutomationNodeKind,
    PlanKind,
    RunSource,
    RunStatus,
)

logger = logging.getLogger(__name__)


def _signed_headers(body_bytes: bytes, secret: str) -> dict[str, str]:
    headers = {"content-type": "application/json"}
    if secret:
        headers["x-radd-signature"] = hmac.new(
            secret.encode(), body_bytes, hashlib.sha256
        ).hexdigest()
    return headers


async def _apply_plan(
    session: AsyncSession,
    plan: _Plan,
    item: WorkItem | None,
    system_user: User,
    *,
    rule_name: str,
) -> "ItemRead | None":
    """Execute one resolved plan. Returns whatever it CREATED, which is what the
    create_item node's `created` port emits — the return value used to be
    discarded, so the new issue was unreachable from the rest of the graph.

    The ITEM rather than its id (spec 120): the id alone cannot say `TD-42`, and
    the key is what a downstream `{{followup.key}}` is for. Everything the caller
    needs is already on the read model the service returned, so this costs
    nothing beyond not throwing it away."""
    if plan.kind is PlanKind.ITEM_UPDATE and plan.item_update is not None and item is not None:
        await items.update_item(session, item.id, plan.item_update, actor=system_user)
        # assign_round_robin advances its team's rotation ONLY on a successful
        # assignment, inside the same SAVEPOINT (`executor._run_action`
        # wrap this call) — so a rolled-back apply does not move the cursor, and
        # the next item in a per-item run sees the advance.
        if plan.cursor_advance is not None:
            await round_robin.advance_cursor(session, *plan.cursor_advance)
    elif plan.kind is PlanKind.COMMENT and plan.comment is not None and item is not None:
        await comments.create_comment(session, item.id, plan.comment, actor=system_user)
    elif plan.kind is PlanKind.LINK and plan.link is not None and item is not None:
        target_id, link_type = plan.link
        await items.add_item_link(
            session, item.id, ItemLinkCreate(target_id=target_id, link_type=link_type), actor=system_user
        )
    elif plan.kind is PlanKind.ARCHIVE and plan.archive is not None and item is not None:
        await items.set_archived(session, item.id, plan.archive, system_user)
    elif plan.kind is PlanKind.WATCH and plan.person is not None and item is not None:
        await notify_service.watch(session, item.id, plan.person)
    elif plan.kind is PlanKind.MOVE and plan.move_to is not None and item is not None:
        result = await bulk.bulk_move_items(
            session, ItemBulkMove(item_ids=[item.id], target_project_id=plan.move_to), system_user
        )
        if result.skipped:
            raise RuntimeError(f"move_to_project: {result.skipped[0].reason}")
    elif plan.kind is PlanKind.CREATE_ITEM and plan.item_create is not None:
        # Emitted item.created is marked automation-caused — the loop guard skips
        # it, so a create_item node cannot retrigger its own graph.
        return await items.create_item(session, plan.item_create, actor=system_user)
    elif plan.kind is PlanKind.HTTP and plan.http is not None:
        url, body, secret = plan.http
        body_bytes = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        async with httpx.AsyncClient(timeout=settings.webhook_timeout) as client:
            response = await client.post(
                url, content=body_bytes, headers=_signed_headers(body_bytes, secret)
            )
            response.raise_for_status()
    elif plan.kind is PlanKind.NOTIFY and plan.notify is not None:
        user_id, message = plan.notify
        await notify_service.create_notification(
            session,
            user_id=user_id,
            type_=NotificationType.AUTOMATION,
            event_id=None,
            item_id=item.id if item is not None else None,
            actor_id=SYSTEM_ACTOR_ID,
            payload={
                "message": message,
                "rule": rule_name,
                **await _notification_item_ref(session, item),
            },
        )
    return None


async def _notification_item_ref(session: AsyncSession, item: WorkItem | None) -> dict[str, str]:
    """`item_key`/`item_title` for the notification payload, resolved at write
    time through `items.item_ref` (RADD-972); an itemless run gets none."""
    if item is None:
        return {}
    ref = await items.item_ref(session, item.id)
    if ref is None:
        return {}
    return {"item_key": str(ref.get("key") or ""), "item_title": str(ref.get("title") or "")}



def _parent_is_not_an_item(event: Event) -> bool:
    """RADD-1248: an item-scoped trigger (comments) fired for a parent that is
    not an item — a page comment, a page discussion reply. That event never had
    an item, so it takes spec 58's itemless path (event gates, universal
    actions) rather than being dropped as "the item vanished"."""
    parent = (event.payload or {}).get("entity_type")
    return bool(parent) and parent != ItemEntity.ITEM.value


def _subjects_of(event: Event) -> dict[str, tuple[uuid.UUID, ...]]:
    """Ids per entity type, read back out of the refs the kernel wrote (RADD-923).

    The payload is the wire; this turns it back into the packet the walk works
    on. Anything shaped like a ref (`{"id": …}`) under a key that names a
    registered entity type counts — which is exactly the set `emit(subjects=…)`
    put there, and nothing else, because a plugin's own data cannot occupy a key
    that collides with a ref (emit refuses it).
    """
    from radd.kernel.registry import registries

    payload = event.payload or {}
    found: dict[str, tuple[uuid.UUID, ...]] = {}
    for entity_type in registries.entity_refs:
        ref = payload.get(entity_type)
        raw = ref.get("id") if isinstance(ref, dict) else None
        if not raw:
            continue
        try:
            found[entity_type] = (uuid.UUID(str(raw)),)
        except ValueError:
            continue  # a non-uuid id (a plugin keyed on something else) is not ours
    return found


# --- per-event application (one transaction per event; the caller commits) ---


async def _seeded_facts(session: AsyncSession, subject: str, subject_id: uuid.UUID):
    """A manual run's stand-in facts, carrying the seeded subject's REF the way
    an event carries it (RADD-1324) — so `{{page.title}}` resolves on a page
    run exactly as it does on a page event."""
    from radd.kernel.registry import registries

    facts = _manual_facts()
    ref = registries.entity_refs.get(subject)
    if ref is None or subject == graph.ITEM_SUBJECT:
        return facts
    resolved = await ref.ref(session, subject_id)
    if resolved is None:
        return facts
    return replace(facts, payload={subject: resolved})


def _matching_kind(event: Event, rules: list) -> list:
    """An event-backed trigger KIND asks each automation whether it wants THIS
    firing (RADD-1323): "webhook received" fires every automation bound to the
    kind, and `matches(node params, payload)` keeps the ones configured for this
    endpoint. A plain event type, or a kind with no matcher, keeps them all."""
    from radd.kernel.registry import registries

    kind = registries.trigger_kinds.get(event.event_type)
    if kind is None or kind.matches is None:
        return rules
    payload = dict(event.payload or {})
    kept = []
    for rule, node_id in rules:
        params = next(
            (dict(node.get("params") or {}) for node in (rule.nodes or []) if str(node.get("id")) == node_id),
            {},
        )
        try:
            wanted = bool(kind.matches(params, payload))
        except Exception:
            logger.exception("automations: trigger kind %s could not match %s", kind.key, rule.name)
            wanted = False
        if wanted:
            kept.append((rule, node_id))
    return kept


async def apply_event(session: AsyncSession, event: Event) -> None:
    """Run every automation whose trigger matched this event, from that trigger node."""
    if not should_process(event):
        return
    if event.event_type == AutomationEvent.SCHEDULED.value:  # spec 69 scheduler path
        await apply_scheduled(session, event)
        return
    rules = await service.rules_for_trigger(
        session, event.event_type, automated=bool(getattr(event, "automated", False))
    )
    # RADD-1315: an automation never reacts to its OWN change, opted in or not —
    # that is a loop by construction, and the depth cap would only bound it.
    caused_by = getattr(event, "automation_rule_id", None)
    rules = [(rule, node_id) for rule, node_id in rules if caused_by is None or rule.id != caused_by]
    rules = _matching_kind(event, rules)
    if not rules:
        return
    system_user = await _system_actor(session, event)
    if system_user is None:
        return
    item = await _resolve_target_item(session, event)
    trigger_spec = catalog.triggers().get(event.event_type)  # None for a trigger KIND's event
    if item is None and trigger_spec is not None and trigger_spec.item_scoped and not _parent_is_not_an_item(event):
        return  # item vanished before the engine caught up
    facts = await _event_facts(session, event)
    subjects = _subjects_of(event)
    # EVERY subject the event names joins the packet (RADD-923), not just the
    # item. An itemless event still runs: gates evaluate, set-arity actions fire.
    if item is not None:
        subjects["item"] = (item.id,)
    initial = Packet(facts=facts, subjects=subjects)
    for rule, node_id in rules:
        # Start at the trigger that MATCHED. A graph may hold several, and the
        # others are separate entry points that this event did not fire — running
        # from all of them would apply the Monday branch to a create event.
        await run_graph(
            session, rule, initial, system_user, start_node_id=node_id,
            source=RunSource.EVENT, event=event,
        )


def _action_node_ids(rule) -> set[str]:
    """Ids of the graph's action nodes — used to answer "did anything actually
    run" without the caller learning the graph's shape."""
    return {
        str(node.get("id"))
        for node in (rule.nodes or [])
        if node.get("kind") == AutomationNodeKind.ACTION.value
    }


async def run_graph(
    session: AsyncSession,
    rule,
    initial: Packet,
    system_user: User,
    *,
    apply: bool = True,
    start_node_id: str | None = None,
    deadline: float | None = None,
    source: RunSource = RunSource.EVENT,
    event: Event | None = None,
) -> executor.RunReport | None:
    """Execute one automation's graph over an initial packet — the single entry
    for event, schedule and manual runs. An APPLYING walk is recorded in the dry
    run's shape (RADD-1266); a walk that raises is recorded as failed and emits
    `automation.run_failed` instead of stalling the consumer. Returns None when
    the stored graph will not load. `deadline` is the intake path's wall-clock
    budget (it holds the project's number lock).
    """
    try:
        nodes, edges, triggers = await executor.load_graph(rule)
    except GraphError:
        logger.exception("automations: %s has an unrunnable graph; skipping", rule.name)
        return None
    # Actions run as the automation's AUTHOR by default (spec 116 "act as"); a
    # node may name someone else, which needed `automation.act_as` on write.
    # Rows predating the column have no author and keep running as the system
    # actor — exactly what they did before (RADD-1450). Only an owner who WAS
    # named and has since gone or been deactivated fails the run closed: the
    # row keeps that identity so nothing silently falls back to the system.
    author = system_user
    owner_id = getattr(rule, "created_by_id", None)
    owner_error = False
    if owner_id is not None:
        found = await session.get(User, owner_id)
        if found is None or not found.active:
            owner_error = True
        else:
            author = found

    trigger = next(
        (t for t in triggers if start_node_id is None or t.id == start_node_id), None
    )
    if trigger is None:
        # The binding pointed at a node the graph no longer has — a stale index
        # row. Logged rather than raised: one bad automation must not stall the
        # consumer for every other.
        logger.warning(
            "automations: %s has no trigger node %r; skipping this run", rule.name, start_node_id
        )
        return None
    started_at = utcnow()
    # RADD-1315: every write this run makes carries WHICH automation made it and
    # at what chain depth — one deeper than the event that started it, when that
    # event was itself another automation's change.
    depth = (int(getattr(event, "automation_depth", 0) or 0) if getattr(event, "automated", False) else 0) + 1
    cause = events.AutomationCause(rule_id=rule.id, depth=depth)
    record = partial(
        runs.record,
        session,
        automation_id=rule.id,
        trigger_node_id=trigger.id,
        source=source,
        event_id=getattr(event, "id", None),
        event_type=getattr(event, "event_type", "") or "",
        started_at=started_at,
        actor_id=author.id,
    )
    try:
        if owner_error:
            raise ValueError("The automation execution account is unavailable; explicitly assign an active owner")
        with events.run_cause(cause):
            report = await executor.walk(
                session,
                nodes=nodes,
                edges=edges,
                trigger=trigger,
                initial=initial,
                system_user=author,
                automation_name=rule.name,
                budget=executor.new_budget(),
                apply=apply,
                deadline=deadline,
            )
    except Exception as exc:
        if not apply:
            raise
        logger.exception("automations: %s failed while running", rule.name)
        error = f"{exc.__class__.__name__}: {exc}"
        await record(status=RunStatus.FAILED, result=None, error=error)
        await _emit_run_failed(session, rule, trigger.id, error, cause)
        return None
    if apply:
        result = await _result_of(
            session, rule, nodes, report, trigger, initial.item_ids[0] if initial.item_ids else None
        )
        keys = await _keys_for(session, report)
        failures = [p.detail for p in report.plans if p.failed]
        await record(
            status=runs.status_of(report),
            result=result,
            error="; ".join(failures),
            item_keys=[keys[i] for i in initial.item_ids if i in keys],
        )
        if failures:
            await _emit_run_failed(session, rule, trigger.id, "; ".join(failures), cause)
    return report


async def _emit_run_failed(
    session: AsyncSession, rule, trigger_node_id: str, error: str, cause: events.AutomationCause
) -> None:
    """The engine's own report of a run that failed. It carries the RUN'S cause
    (RADD-1450) — which rule, at what chain depth — so the audit log can say
    whose run broke, and a trigger on it sits at the right depth; before, it was
    emitted outside the run's scope and read as an anonymous depth-1 automation."""
    with events.automated(cause=cause):
        await events.emit(
            session,
            event_type=AutomationEvent.RUN_FAILED,
            entity_type=AutomationEntity.RULE,
            entity_id=rule.id,
            actor_id=SYSTEM_ACTOR_ID,
            payload={"name": rule.name, "trigger_node_id": trigger_node_id, "error": error},
        )


async def _system_actor(session: AsyncSession, event: Event) -> User | None:
    """The system actor, or None (logged) when the migration has not seeded it."""
    system_user = await session.get(User, SYSTEM_ACTOR_ID)
    if system_user is None:
        logger.error(
            "automations: system actor %s missing — run the migration; skipping event %s",
            SYSTEM_ACTOR_ID,
            event.id,
        )
    return system_user


def _scheduled_facts(event: Event) -> conditions.EventFacts:
    """Facts for a scheduled run's templates: the system actor + the synthetic
    payload (`rule_id`, `node_id`, `scheduled_for`)."""
    return conditions.EventFacts(
        event_type=event.event_type,
        actor_id=str(SYSTEM_ACTOR_ID),
        actor_email=SYSTEM_ACTOR_EMAIL,
        actor_name=SYSTEM_ACTOR_NAME,
        payload=dict(event.payload or {}),
    )


async def apply_scheduled(session: AsyncSession, event: Event) -> None:
    """Execute the payload rule of one `automation.scheduled` event (spec 69).

    A schedule has no event and produces no items of its own (RADD-1265): the
    trigger hands an EMPTY packet downstream, and a `search.slq` node wired
    after it is what selects the items a run acts on — visible on the canvas
    rather than buried in the trigger's form. Every resulting item event carries
    the SYSTEM actor, so event rules still skip them (the loop guard holds)."""
    payload = event.payload or {}
    try:
        rule_id = uuid.UUID(str(payload.get("rule_id")))
    except ValueError:
        logger.warning("automations: scheduled event %s has no valid rule_id", event.id)
        return
    node_id = str(payload.get("node_id") or "")
    rule = await session.get(Automation, rule_id)
    if rule is None or not rule.enabled:
        return  # deleted / disabled between emit and consume
    system_user = await _system_actor(session, event)
    if system_user is None:
        return
    # An empty packet: item actions skip, universal actions fire, which is how
    # "post to chat every Monday" works with no items involved at all, and a
    # search node is how "every stale issue" gets its set.
    initial = Packet.of(_scheduled_facts(event), item=())
    await run_graph(
        session, rule, initial, system_user, start_node_id=node_id or None,
        source=RunSource.SCHEDULE, event=event,
    )


async def run_manual(
    session: AsyncSession,
    rule: Automation,
    item_id: uuid.UUID,
    *,
    start_node_id: str | None = None,
    subject: str = "item",
) -> bool:
    """Run a MANUAL rule on one item, on demand (the editor `/` quick-action seam,
    POST /automations/{id}/run). The graph's filters are still respected — returns
    False when nothing reached an action, True when actions were executed.

    `start_node_id` is the manual TRIGGER node. A graph may hold several entry
    points, and starting at whichever came first would run the Monday branch when
    somebody pressed a button."""
    if subject == graph.ITEM_SUBJECT:
        item_id = (await items.require_item(session, item_id)).id
    system_user = await session.get(User, SYSTEM_ACTOR_ID)
    if system_user is None:
        raise RuntimeError("automations: system actor missing — run the migration")
    # RADD-1323: any subject the manual kind seeds — a page run carries the page.
    report = await run_graph(
        session,
        rule,
        Packet.of(await _seeded_facts(session, subject, item_id), **{subject: (item_id,)}),
        system_user,
        start_node_id=start_node_id,
        source=RunSource.MANUAL,
    )
    if report is None:
        return False
    # "Did it apply" = did any action node resolve on this run (RADD-1323: asked of
    # the plans, since a page-seeded run carries no items).
    actions = _action_node_ids(rule)
    return any(plan.resolves for plan in report.plans if plan.node_id in actions)


# --- poll iteration (mirrors webhooks.service.fanout_events; one txn per event) ---


async def run_once(session_factory=SessionLocal) -> int:
    """Consume one batch: apply each triggering event in its own transaction, then advance
    the cursor. Returns the number of events consumed."""
    async with session_factory() as session:
        offset = await events.get_offset(session, CONSUMER_NAME)
        batch = await events.read_after(session, offset, settings.automation_batch)
    if not batch:
        return 0
    for event in batch:
        if not should_process(event):
            continue
        try:
            async with session_factory() as session:
                await apply_event(session, event)
                await session.commit()
        except Exception:
            logger.exception("automations: failed processing event %s", event.id)
    async with session_factory() as session:
        await events.set_offset(session, CONSUMER_NAME, batch[-1].id)
        await session.commit()
    return len(batch)


# --- dry-run preview (POST /automations/{id}/test) ---


async def preview(
    session: AsyncSession,
    rule: Automation,
    item_id: uuid.UUID | None = None,
    trigger_node_id: str | None = None,
    *,
    subject: str = "item",
    subject_id: uuid.UUID | None = None,
    event_id: int | None = None,
    event_payload: dict | None = None,
    project_id: uuid.UUID | None = None,
) -> RuleTestResult:
    """Walk the graph with the appliers off and report what each node did. The
    seed is optional (RADD-921): search- and schedule-fed graphs have none. Nodes
    that are not `preview_safe` are skipped, and branches needing created objects
    are reported as unavailable. Recorded events supply real facts."""
    system_user = await session.get(User, SYSTEM_ACTOR_ID)
    try:
        nodes, _edges, triggers = await executor.load_graph(rule)
    except GraphError:
        return RuleTestResult(rule_id=rule.id, item_id=item_id, matched=False, would_apply=[])

    trigger = next(
        (t for t in triggers if trigger_node_id is None or t.id == trigger_node_id),
        None,
    )
    seed: tuple[uuid.UUID, ...] = ()
    if item_id is not None:
        seed = ((await items.require_item(session, item_id)).id,)
    subjects = {"item": seed}
    if subject != graph.ITEM_SUBJECT and subject_id is not None:
        subjects = {subject: (subject_id,)}  # RADD-1323: a page's dry run

    if trigger is None:
        raise ValueError("Choose a trigger that exists in this graph")
    facts = await _seeded_facts(session, subject, subject_id) if subject != graph.ITEM_SUBJECT and subject_id else _manual_facts()
    if project_id is not None:
        subjects["project"] = (project_id,)
    if event_id is not None:
        event = await session.get(Event, event_id)
        if event is None or event.event_type != str(trigger.params.get("event")):
            raise ValueError("Choose a recorded event matching this trigger")
        facts, subjects = await _event_facts(session, event), _subjects_of(event)
        target = await _resolve_target_item(session, event)
        if target is not None:
            subjects["item"] = (target.id,)
    elif event_payload is not None:
        facts = replace(facts, event_type=str(trigger.params.get("event") or "manual"), payload=event_payload)
    report = await run_graph(
        session,
        rule,
        Packet.of(facts, **subjects),
        system_user,
        apply=False,
        start_node_id=trigger.id if trigger is not None else None,
    )
    if report is None:
        return RuleTestResult(rule_id=rule.id, item_id=item_id, matched=False, would_apply=[])
    return await _result_of(session, rule, nodes, report, trigger, item_id)


async def _result_of(
    session: AsyncSession,
    rule: Automation,
    nodes: list,
    report: executor.RunReport,
    trigger,
    item_id: uuid.UUID | None,
) -> RuleTestResult:
    """The report as the API and the run history show it — ONE builder for the
    dry run and the recorded run (RADD-1266), so the two cannot describe the
    same walk differently."""
    keys = await _keys_for(session, report)
    previews: list[ActionPreview] = []
    for planned in report.plans:
        # The node TYPE (RADD-1322: `action.set_state`, `page.comment`) — one
        # vocabulary for built-in and contributed actions alike.
        previews.append(
            ActionPreview(
                type=planned.action_type,
                params=planned.params,
                resolves=planned.resolves,
                refused=planned.refused,
                failed=planned.failed,
                detail=planned.detail,
                node_id=planned.node_id,
                item_key=keys.get(planned.item_id, "") if planned.item_id else "",
                resolved=dict(planned.resolved),
            )
        )

    return RuleTestResult(
        rule_id=rule.id,
        item_id=item_id,
        matched=bool(previews) or bool(report.findings),
        would_apply=previews,
        trigger_node_id=trigger.id if trigger is not None else "",
        nodes=_node_results(nodes, report, keys),
        dropped=list(report.dropped),
        # A validation graph's whole output (spec 119). Without this a dry run
        # of one reports port counts and no actions — accurate, and useless.
        findings=[
            TestFinding(node_id=f.node_id, message=f.message, field=f.field)
            for f in report.findings
        ],
    )


async def _keys_for(
    session: AsyncSession, report: executor.RunReport
) -> dict[uuid.UUID, str]:
    """`TD-42` for every item the report mentions, in ONE query.

    Keys rather than ids in the response because the point of a sample is that
    someone recognises it, and nobody recognises a uuid."""
    wanted: set[uuid.UUID] = set()
    for ids in report.incoming_items.values():
        wanted.update(ids)
    for ports in report.port_items.values():
        for ids in ports.values():
            wanted.update(ids)
    wanted.update(plan.item_id for plan in report.plans if plan.item_id is not None)
    if not wanted:
        return {}
    rows = (
        await session.execute(
            select(WorkItem.id, Project.key, WorkItem.number)
            .join(Project, Project.id == WorkItem.project_id)
            .where(WorkItem.id.in_(wanted))
        )
    ).all()
    return {item_id: f"{key}-{number}" for item_id, key, number in rows}


def _produced(node, report: executor.RunReport) -> list[ProducedVar]:
    """What this node made addressable, with the token that reads it (spec 120).

    An UNNAMED producer still reports its values, with an empty token: the point
    of showing them is that someone can see the node produced something and that
    nothing can read it yet."""
    name = output_name(node)
    return [
        ProducedVar(
            token=f"{{{{{name}.{field}}}}}" if name else "",
            name=field,
            value=value,
        )
        for field, value in (report.produced.get(node.id) or {}).items()
    ]


def _node_results(
    nodes: list, report: executor.RunReport, keys: dict[uuid.UUID, str]
) -> list[NodeResult]:
    """Every node of the graph, including the ones that never ran.

    Absent-from-the-report and ran-with-nothing are different answers — the first
    means the branch was never reached — so the list covers the whole graph
    rather than only what the walk touched."""
    sample = lambda ids: [keys[i] for i in ids if i in keys]  # noqa: E731
    results: list[NodeResult] = []
    for node in nodes:
        counts = report.per_node.get(node.id)
        untaken = set(report.not_taken.get(node.id, ()))
        emitted = report.port_items.get(node.id, {})
        results.append(
            NodeResult(
                node_id=node.id,
                kind=node.kind.value,
                type=node.type,
                name=output_name(node),
                produced=_produced(node, report),
                ran=counts is not None,
                incoming=(counts or {}).get("in", 0),
                incoming_sample=sample(report.incoming_items.get(node.id, ())),
                ports=[
                    PortResult(
                        port=port,
                        # The EXACT count from the walk, not the length of the
                        # capped sample — a filter that matched 200 must not
                        # report 10 because that is all the report kept.
                        count=(counts or {}).get(port, 0),
                        sample=sample(emitted.get(port, ())),
                        taken=port not in untaken,
                    )
                    for port in ports_of(node)
                ]
                if counts is not None
                else [],
            )
        )
    return results
