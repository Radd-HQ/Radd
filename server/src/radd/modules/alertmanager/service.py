"""Alertmanager intake (RADD-1317): receivers as rows; a delivery creates the alert's
issue, maps the fingerprint and fires `alertmanager.alert.*`. Beyond that a receiver
does only what its settings say (RADD-1370, off by default): label, internal
comment, resolve move."""

import hmac
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd import secretbox
from radd.config import settings
from radd.db import SessionLocal
from radd.exceptions import ConflictError, NotFoundError
from radd.kernel import changes
from radd.modules.auth import service as auth
from radd.modules.automations.intake import suppressed as intake_suppressed
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.comments import service as comments
from radd.modules.comments.schemas import CommentCreate
from radd.modules.comments.types import CommentVisibility
from radd.modules.events import service as events
from radd.modules.items import service as items
from radd.modules.items.enums import ItemOrigin
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.projects import service as projects_service
from radd.modules.workflow import service as workflow
from radd.snapshot import Snapshot

from . import planner
from .models import AlertItem, AlertReceiver
from .types import (
    RESOLVED_COMMENT,
    STILL_FIRING_COMMENT,
    AlertAction,
    AlertEntity,
    AlertmanagerEvent,
    AlertTrigger,
)

logger = logging.getLogger(__name__)

_TRIGGER_OF = {
    AlertAction.CREATE: AlertTrigger.FIRING,
    AlertAction.STILL_FIRING: AlertTrigger.REPEATED,
    AlertAction.RESOLVED: AlertTrigger.RESOLVED,
}


# --- the webhook ----------------------------------------------------------------


async def receiver_for_token(session: AsyncSession, token: str) -> AlertReceiver | None:
    """The ACTIVE receiver whose token this is — compared constant-time against
    each, so the answer does not depend on how early the match is. The one place
    a token is decrypted (RADD-1446); a row that will not decrypt matches nothing
    and is logged, so one damaged receiver never takes the webhook down."""
    supplied = (token or "").strip()
    if not supplied:
        return None
    found: AlertReceiver | None = None
    for receiver in (await session.execute(select(AlertReceiver).where(AlertReceiver.active))).scalars():
        if not receiver.token:
            continue
        try:
            stored = secretbox.decrypt(receiver.token)
        except secretbox.SecretBoxError as exc:
            logger.warning("alertmanager: receiver %r token does not decrypt: %s", receiver.name, exc)
            continue
        if hmac.compare_digest(supplied, stored):
            found = receiver
    return found


async def process(session: AsyncSession, receiver: AlertReceiver, payload: dict) -> dict[str, int]:
    """Plan (pure) + apply one Alertmanager delivery for this receiver."""
    fingerprints = {alert.get("fingerprint", "") for alert in payload.get("alerts") or []} - {""}
    # Serialize deliveries for this receiver so concurrent repeats cannot both
    # create an issue before either deduplication mapping is visible.
    await session.execute(select(AlertReceiver.id).where(AlertReceiver.id == receiver.id).with_for_update())
    known = await _known_items(session, receiver.id, fingerprints)
    plans = planner.plan_alerts(payload, existing=frozenset(known))
    if not plans:
        return {"created": 0, "triggered": 0}
    if receiver.project_id is None:
        raise ConflictError(AlertEntity.RECEIVER, reason=f"receiver {receiver.name!r} has no project")
    actor = await auth.get_user(session, SYSTEM_ACTOR_ID)
    created = triggered = commented = moved = 0
    for plan in plans:
        if plan.action is AlertAction.CREATE:
            # Machine intake is not human intake (spec 119): a monitoring system
            # cannot be asked for repro steps, and refusing it is a 5xx it retries.
            with intake_suppressed(), items.creating_from(ItemOrigin.ALERT):
                item = await items.create_item(
                    session,
                    ItemCreate(
                        project_id=receiver.project_id, title=plan.title, description=plan.description,
                        labels=[receiver.label] if receiver.label else [],
                    ),
                    actor,
                )
            session.add(AlertItem(fingerprint=plan.fingerprint, item_id=item.id, receiver_id=receiver.id))
            await session.flush()
            known[plan.fingerprint] = item.id
            created += 1
        await events.emit(
            session,
            event_type=_TRIGGER_OF[plan.action],
            entity_type=AlertEntity.ALERT,
            entity_id=plan.fingerprint,
            actor_id=SYSTEM_ACTOR_ID,
            subjects={"item": known[plan.fingerprint]},
            payload=planner.facts_of(plan, receiver.name),
        )
        triggered += 1
        if plan.action is not AlertAction.CREATE:
            commented += await _comment(session, receiver, plan, known[plan.fingerprint], actor)
        if plan.action is AlertAction.RESOLVED:
            moved += await _move_resolved(session, receiver, known[plan.fingerprint], actor)
    result = {"created": created, "triggered": triggered}
    if receiver.comment_updates:
        result["commented"] = commented
    if receiver.resolve_state_id is not None:
        result["moved"] = moved
    return result


async def _comment(session: AsyncSession, receiver: AlertReceiver, plan, item_id: uuid.UUID, actor) -> int:
    """RADD-1370: an INTERNAL note on a repeat or a resolution, when the
    receiver's `comment_updates` is on — operational noise stays off anything a
    requester could be mailed."""
    if not receiver.comment_updates:
        return 0
    body = RESOLVED_COMMENT if plan.action is AlertAction.RESOLVED else STILL_FIRING_COMMENT.format(count=plan.firing_count)
    await comments.create_comment(
        session, item_id, CommentCreate(body=body, visibility=CommentVisibility.INTERNAL), actor
    )
    return 1


async def _move_resolved(session: AsyncSession, receiver: AlertReceiver, item_id: uuid.UUID, actor) -> int:
    """RADD-1370: move a resolved alert's issue to the receiver's resolve state.
    A state that no longer belongs to the issue's project (the receiver was
    pointed elsewhere since) is skipped; a refused transition keeps the delivery."""
    target = receiver.resolve_state_id
    if target is None:
        return 0
    item = await items.require_item(session, item_id)
    if item.state_id == target:
        return 0
    if target not in {state.id for state in await workflow.list_states(session, item.project_id)}:
        logger.warning("alertmanager: resolve state of %s is not in the issue's project", receiver.name)
        return 0
    try:
        async with session.begin_nested():
            await items.update_item(session, item.id, ItemUpdate(state_id=target), actor)
    except Exception:  # noqa: BLE001 — a guard refusing one move must not lose the delivery
        logger.exception("alertmanager: resolve transition failed for item %s", item.id)
        return 0
    return 1


async def _known_items(session: AsyncSession, receiver_id: uuid.UUID, fingerprints: set[str]) -> dict[str, uuid.UUID]:
    if not fingerprints:
        return {}
    result = await session.execute(
        select(AlertItem.fingerprint, AlertItem.item_id).where(
            AlertItem.receiver_id == receiver_id, AlertItem.fingerprint.in_(fingerprints)
        )
    )
    return dict(result.all())


# --- receivers ------------------------------------------------------------------

#: A diff records that the token CHANGED, never its value.
SECRET_FIELDS: tuple[str, ...] = ("token",)


async def list_receivers(session: AsyncSession) -> list[AlertReceiver]:
    return list((await session.execute(select(AlertReceiver).order_by(AlertReceiver.name))).scalars())


async def get_receiver(session: AsyncSession, receiver_id: uuid.UUID) -> AlertReceiver:
    receiver = await session.get(AlertReceiver, receiver_id)
    if receiver is None:
        raise NotFoundError(AlertEntity.RECEIVER, receiver_id)
    return receiver


async def _emit(session, event_type, receiver: AlertReceiver, actor_id, diff=None) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=AlertEntity.RECEIVER,
        entity_id=receiver.id,
        actor_id=actor_id,
        payload={"name": receiver.name},
        changes=diff,
    )


#: What a receiver diff reports (spec 123); the token only as "changed".
_AUDITED = ("name", "token", "project_id", "active", "comment_updates", "label", "resolve_state_id")


async def _check_resolve_state(session: AsyncSession, receiver: AlertReceiver) -> None:
    """The resolve state must be one of the receiver's project's states."""
    if receiver.resolve_state_id is None:
        return
    states = await workflow.list_states(session, receiver.project_id) if receiver.project_id else []
    if receiver.resolve_state_id not in {state.id for state in states}:
        raise ConflictError(AlertEntity.RECEIVER, reason="the resolve state must belong to the receiver's project")


async def create_receiver(session: AsyncSession, data, *, actor_id: uuid.UUID | None = None) -> AlertReceiver:
    await _claim_seed(session)
    if (await session.execute(select(AlertReceiver).where(AlertReceiver.name == data.name))).scalar_one_or_none():
        raise ConflictError(AlertEntity.RECEIVER, data.name)
    receiver = AlertReceiver(
        name=data.name, token=secretbox.seal(data.token), project_id=data.project_id, active=data.active,
        comment_updates=data.comment_updates, label=data.label.strip(), resolve_state_id=data.resolve_state_id,
    )
    await _check_resolve_state(session, receiver)
    session.add(receiver)
    await session.flush()
    await refresh_snapshot(session)
    await _emit(session, AlertmanagerEvent.RECEIVER_CREATED, receiver, actor_id)
    return receiver


async def update_receiver(session: AsyncSession, receiver_id: uuid.UUID, data, *, actor_id=None) -> AlertReceiver:
    receiver = await get_receiver(session, receiver_id)
    # A token stored before RADD-1446 takes its encrypted form on this save — before
    # the snapshot, so the adoption itself is not recorded as a change.
    receiver.token = secretbox.adopt(receiver.token)
    before = changes.snapshot(receiver, _AUDITED)
    fields = data.model_dump(exclude_unset=True)
    if secretbox.keeps_secret(fields.get("token")):
        fields.pop("token", None)  # `KEEP_SECRET` on update keeps the stored token
    else:
        fields["token"] = secretbox.seal(fields["token"])
    if fields.get("label") is not None:
        fields["label"] = fields["label"].strip()
    for key, value in fields.items():
        setattr(receiver, key, value)
    if "project_id" in fields and "resolve_state_id" not in fields:
        receiver.resolve_state_id = None  # a new project has its own states
    await _check_resolve_state(session, receiver)
    await session.flush()
    await refresh_snapshot(session)
    await _emit(
        session, AlertmanagerEvent.RECEIVER_UPDATED, receiver, actor_id,
        changes.diff_object(receiver, before, hidden=SECRET_FIELDS),
    )
    return receiver


async def delete_receiver(session: AsyncSession, receiver_id: uuid.UUID, *, actor_id=None) -> None:
    receiver = await get_receiver(session, receiver_id)
    await _emit(session, AlertmanagerEvent.RECEIVER_DELETED, receiver, actor_id)
    await session.delete(receiver)
    await session.flush()
    await refresh_snapshot(session)


# --- capability snapshot, startup sweep + env seed ----------------------------


async def encrypt_plaintext_tokens() -> None:
    """Tokens saved before RADD-1446 take their encrypted form. A missing secretbox
    key logs and skips — boot never waits on it."""
    try:
        async with SessionLocal() as session:
            for receiver in await list_receivers(session):
                receiver.token = secretbox.adopt(receiver.token)
            await session.commit()
    except secretbox.SecretBoxError as exc:
        logger.warning("alertmanager: receiver tokens stay plaintext this boot: %s", exc)


async def _load_active_count() -> int:
    async with SessionLocal() as session:
        rows = await session.execute(select(func.count()).select_from(AlertReceiver).where(AlertReceiver.active))
        return int(rows.scalar_one())


_active: Snapshot[int] = Snapshot("alertmanager.active-receivers", _load_active_count, initial=0)


def active_receiver_count() -> int:
    return _active.get()


async def refresh_snapshot(session: AsyncSession) -> None:
    rows = await session.execute(select(func.count()).select_from(AlertReceiver).where(AlertReceiver.active))
    _active.set(int(rows.scalar_one()))


async def seed_from_env() -> None:
    """`RADD_ALERTMANAGER_TOKEN` + `_PROJECT_KEY` become ONE receiver row, once,
    when the table is empty (the spec-101 rule) — an instance that ran spec 47
    from the environment keeps receiving across the upgrade, and an admin who
    deletes the row never sees it return."""
    token = settings.alertmanager_token.strip()
    async with SessionLocal() as session:
        empty = int((await session.execute(select(func.count()).select_from(AlertReceiver))).scalar_one()) == 0
        claimed = await _claim_seed(session) if token or not empty else False
        if token and empty and claimed:
            project_id = None
            key = settings.alertmanager_project_key.strip()
            if key:
                try:
                    project_id = (await projects_service.get_by_key(session, key)).id
                except NotFoundError:
                    logger.warning("alertmanager: seed project %s does not exist; receiver has no project", key)
            session.add(
                AlertReceiver(name="Alertmanager", token=secretbox.seal(token), project_id=project_id, active=True)
            )
            logger.info("alertmanager: seeded one receiver from the environment")
        await session.commit()
        await refresh_snapshot(session)


async def _claim_seed(session: AsyncSession) -> bool:
    from sqlalchemy.dialects.postgresql import insert
    from .models import AlertSeed

    claimed = await session.scalar(insert(AlertSeed).values(key="environment")
                                   .on_conflict_do_nothing().returning(AlertSeed.key))
    return claimed is not None
