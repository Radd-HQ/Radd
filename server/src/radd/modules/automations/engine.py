"""The automation engine: an outbox consumer that walks each matching
automation's GRAPH and applies what its action nodes plan, as the system actor.

Loop guard (critical): every engine-applied mutation emits its item event with
`actor_id = SYSTEM_ACTOR_ID`. `should_process` skips those, so an automation whose
action sets a field it also matches on applies exactly once and never spins.

Best-effort: each action runs inside a SAVEPOINT — a failing action rolls back only
itself, is logged, and the rest continue; the engine never crashes on bad data.

Spec 116 (RADD-914): the three entry points — event, schedule and manual — all
build an initial `Packet` and hand it to `run_graph`, so the branching semantics
live in ONE place (`executor.walk`) rather than being re-implemented per caller.
That is also why `preview` is now a real dry run: it walks the same graph with
`apply=False`, so what it shows is what a live run decides, not a second opinion.

RADD-902: trigger classification, condition matching, and the read-only action
planner (`_plan`/`_Plan`) live in `planning.py` — the planning-vs-applying seam
the audit named as this file's cleanest cut. Application (`apply_event`/
`_apply_plan`/`run_graph`), scheduled runs, poll iteration, and the dry-run
preview stay here, and this module re-exports everything `planning.py` defines
under its own name — `from radd.modules.automations.engine import _plan,
condition_matches, should_process, ...` (real callers: `router.py`,
`dispatcher.py`, and several tests) is unaffected.
"""

import hashlib
import hmac
import json
import logging
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

from . import catalog, conditions, executor, round_robin, runs, service
from .graph import GraphError, Packet
from .models import Automation
from .planning import (
    _Plan,
    _cycle_by_name as _cycle_by_name,
    _current_labels as _current_labels,
    _event_facts,
    _is_clear as _is_clear,
    _item_ctx as _item_ctx,
    _manual_facts as _manual_facts,
    _plan as _plan,
    _project_by_key as _project_by_key,
    _project_definitions as _project_definitions,
    _resolve_target_item,
    _state_by_name as _state_by_name,
    _team_by_name as _team_by_name,
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
    ActionType,
    AutomationEntity,
    AutomationEvent,
    AutomationNodeKind,
    PlanKind,
    RunSource,
    RunStatus,
)

logger = logging.getLogger(__name__)


async def _send_email(
    session: AsyncSession, to_address: str, to_name: str, subject: str, body: str
) -> None:
    """The send_email action's delivery, through the ONE transport (RADD-983).

    It used to dial `radd.smtp` off the environment, which made it the third
    sender that a rows-only instance — Settings → Email configured, no
    `RADD_SMTP_*` — silently never sent from. `mailintake.service` resolves the
    default sender ROW first and falls back to the environment relay, so both
    shapes work and neither needs a branch here.

    Itemless on purpose. The action's `to` may be a literal address at SET
    arity, i.e. about no single issue, and the rendered subject and body are
    already the caller's own — so there is no conversation to thread onto and
    `send_plain_mail` is the right half of the transport. (A per-item run to a
    role is still itemless mail: the message is the rule's text, not a reply on
    the ticket's thread, and threading it would file an unrelated announcement
    into the customer's conversation.)

    **Loop safety is unchanged and is now load-bearing.** The comment this
    replaces read "nothing is emitted — inherently loop-safe", and that stopped
    being true the moment the transport started emitting `mail.sent`/
    `mail.failed`, which ARE automation triggers. What holds is
    `executor._one`: `_apply_plan` runs inside `with events.automated()`, so
    every event this send emits is marked automation-caused and
    `planning.should_process` rejects it. A rule triggered on "Email sent"
    therefore cannot be fired by an automation's own email.

    Reached DEFERRED and feature-detected — mailintake is optional and
    disableable, the shape `email_action.py` uses for the `contact` role. With
    the module absent the send is skip-logged rather than crashing the branch;
    it is not silently swallowed, because a rule that stopped emailing with no
    trace is exactly the failure this issue is about.
    """
    from .email_action import mailintake_service

    mail_service = mailintake_service()
    if mail_service is None:
        logger.info(
            "automations: send_email to %s skipped — the mailintake module is not loaded",
            to_address,
        )
        return
    sent = await mail_service.send_plain_mail(
        session, to_address=to_address, to_name=to_name, subject=subject, text=body
    )
    if sent is None:
        logger.warning("automations: send_email to %s was not delivered", to_address)


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
        # assignment, inside the same SAVEPOINT (`_one`/`_run_contributed_action`
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
    elif plan.kind is PlanKind.PARTICIPANT and plan.person is not None and item is not None:
        # Feature-detected like mailintake: participants is a service-desk
        # module an instance may not load, and the seam must not import it
        # at module load.
        from .email_action import participants_service

        participants = participants_service()
        if participants is None:
            logger.info("automations: add_participant skipped — the participants module is not loaded")
            return None
        await participants.add_participant(
            session, item.id, participants.ParticipantAdd(user_id=plan.person), system_user
        )
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
    elif plan.kind is PlanKind.EMAIL and plan.email is not None:
        to_address, to_name, subject, body = plan.email
        await _send_email(session, to_address, to_name, subject, body)
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
    """The `item_key`/`item_title` pair every other item-scoped notification
    carries (RADD-972) — display values resolved at WRITE time, spec 26's rule.

    The row already had `item_id`, but nothing that composes a line from the
    payload (the digest, the per-event email) does a lookup — that is the rule,
    and the automation type was the one exception to it, so its email line
    could name the rule that fired and not the issue it fired on. Read through
    `items.item_ref`, the seam every emitter uses for the same pair, rather than
    joining the project here: the key's spelling is items' to own.

    An itemless rule (a schedule at set arity, a universal action) has no ref
    and gets none; the renderers' linkless degradation stays for that case.
    """
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


async def apply_event(session: AsyncSession, event: Event) -> None:
    """Run every matching rule's actions for one event, best-effort. Any catalog
    trigger is subscribable (spec 58): the rule's event conditions gate on the
    event itself; when a target item resolves, the SLQ condition and the item
    actions apply to it — a matching rule on an itemless event logs and skips
    its actions (they are all item-bound today)."""
    if not should_process(event):
        return
    if event.event_type == AutomationEvent.SCHEDULED.value:  # spec 69 scheduler path
        await apply_scheduled(session, event)
        return
    rules = await service.rules_for_trigger(session, event.event_type)
    if not rules:
        return
    system_user = await session.get(User, SYSTEM_ACTOR_ID)
    if system_user is None:
        logger.error(
            "automations: system actor %s missing — run the migration; skipping event %s",
            SYSTEM_ACTOR_ID,
            event.id,
        )
        return
    item = await _resolve_target_item(session, event)
    if item is None and catalog.TRIGGERS[event.event_type].item_scoped and not _parent_is_not_an_item(event):
        return  # item vanished before the engine caught up
    facts = await _event_facts(session, event)
    subjects = _subjects_of(event)
    # EVERY subject the event names becomes part of the packet (RADD-923), not
    # just the item — so an event about a deployment carries the deployment, the
    # release AND the item, and a contributed action node declaring
    # `subject="deployment"` is handed exactly those ids.
    #
    # An itemless event still runs the graph, carrying an empty item set: gates
    # evaluate, and universal actions fire. That is spec 116's "empty sets
    # propagate", and it is what preserves the pre-graph behaviour where a
    # webhook action ran on an event with no item.
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
    """Execute one automation's graph over an initial packet.

    An APPLYING walk is RECORDED (RADD-1266): the report the walk builds is
    stored in the dry run's own shape, in the same transaction as the run, so
    "what did it do" is answered by the panel that answers "what would it do".
    A dry run (`apply=False`) writes nothing — a validation walk included. A
    walk that RAISES is recorded as failed and emits `automation.run_failed`
    rather than escaping into the consumer loop, so one broken automation does
    not stall every other rule for the same event.

    Every entry point funnels through here — event, schedule and manual — so the
    branching semantics are defined once. Returns None when the stored graph will
    not load, which is a data problem to log rather than an exception to escape
    into the consumer loop and stall the cursor.

    `deadline` is a wall-clock budget the intake path sets (spec 119): its walk
    runs inside a request that is holding the project's number lock, so a node
    waiting on a model has to be told when to stop waiting. The consumer and the
    scheduler pass none — nothing is blocked on them.
    """
    try:
        nodes, edges, triggers = await executor.load_graph(rule)
    except GraphError:
        logger.exception("automations: %s has an unrunnable graph; skipping", rule.name)
        return None
    # Actions run as the automation's AUTHOR by default (spec 116 "act as"); a
    # node may name someone else, which needed `automation.act_as` on write.
    # Rows predating the column have no author and keep running as the system
    # actor — exactly what they did before.
    author = system_user
    if getattr(rule, "created_by_id", None):
        found = await session.get(User, rule.created_by_id)
        if found is not None and found.active:
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
    try:
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
        await runs.record(
            session,
            automation_id=rule.id,
            trigger_node_id=trigger.id,
            source=source,
            event_id=getattr(event, "id", None),
            event_type=getattr(event, "event_type", "") or "",
            started_at=started_at,
            actor_id=author.id,
            status=RunStatus.FAILED,
            result=None,
            error=error,
        )
        await events.emit(
            session,
            event_type=AutomationEvent.RUN_FAILED,
            entity_type=AutomationEntity.RULE,
            entity_id=rule.id,
            actor_id=SYSTEM_ACTOR_ID,
            payload={"name": rule.name, "trigger_node_id": trigger.id, "error": error},
        )
        return None
    if apply:
        result = await _result_of(
            session, rule, nodes, report, trigger, initial.item_ids[0] if initial.item_ids else None
        )
        keys = await _keys_for(session, report)
        await runs.record(
            session,
            automation_id=rule.id,
            trigger_node_id=trigger.id,
            source=source,
            event_id=getattr(event, "id", None),
            event_type=getattr(event, "event_type", "") or "",
            started_at=started_at,
            actor_id=author.id,
            status=runs.status_of(report),
            result=result,
            item_keys=[keys[i] for i in initial.item_ids if i in keys],
        )
    return report


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
    system_user = await session.get(User, SYSTEM_ACTOR_ID)
    if system_user is None:
        logger.error(
            "automations: system actor %s missing — run the migration; skipping event %s",
            SYSTEM_ACTOR_ID,
            event.id,
        )
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
) -> bool:
    """Run a MANUAL rule on one item, on demand (the editor `/` quick-action seam,
    POST /automations/{id}/run). The graph's filters are still respected — returns
    False when nothing reached an action, True when actions were executed.

    `start_node_id` is the manual TRIGGER node. A graph may hold several entry
    points, and starting at whichever came first would run the Monday branch when
    somebody pressed a button."""
    item = await items.require_item(session, item_id)
    system_user = await session.get(User, SYSTEM_ACTOR_ID)
    if system_user is None:
        raise RuntimeError("automations: system actor missing — run the migration")
    report = await run_graph(
        session,
        rule,
        Packet.of(_manual_facts(), item=(item.id,)),
        system_user,
        start_node_id=start_node_id,
        source=RunSource.MANUAL,
    )
    if report is None:
        return False
    # "Did it apply?" used to mean "did the one SLQ condition match". A graph has
    # no single condition, so the honest answer is whether any action node was
    # actually reached with this item — which is also what the caller shows the
    # person who pressed the button.
    return any(counts.get("in", 0) > 0 for node_id, counts in report.per_node.items()
               if node_id in _action_node_ids(rule))


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
) -> RuleTestResult:
    """Walk the graph with the appliers off, and report what each node did.

    Nothing is special-cased for preview: the same nodes make the same decisions
    and only `_apply_plan` is skipped, so this shows what a real run WOULD do
    rather than a second implementation's opinion of it.

    The seed item is optional (RADD-921). A graph fed by a search node or a
    schedule trigger has no triggering item, and requiring one made exactly those
    graphs — the ones with a query worth checking — the ones that could not be
    dry-run. The walk starts from the given item, or from nothing, and a search
    node produces what it would on a real run.
    """
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

    report = await run_graph(
        session,
        rule,
        Packet.of(_manual_facts(), item=seed),
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
        try:
            action_type = ActionType(planned.action_type)
        except ValueError:
            continue  # a node type this build does not know
        previews.append(
            ActionPreview(
                type=action_type,
                params=planned.params,
                resolves=planned.resolves,
                refused=planned.refused,
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
