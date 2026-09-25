"""Alertmanager intake (spec 47, rebuilt RADD-1317): receivers as rows, and a
receiver that records alerts and FIRES TRIGGERS — nothing else.

It used to comment on the issue for every repeat and resolution, transition it
on resolve to a state NAMED in an env var, and hardcode an `alert` label — the
same unasked behaviour RADD-1309 took out of the VCS connectors. Now the issue
is created (someone has to see the alert), the fingerprint is mapped, and
`alertmanager.alert.firing|repeated|resolved` fire with the alert's facts. The
old behaviours are this plugin's automation templates.
"""

import hmac
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.exceptions import ConflictError, NotFoundError
from radd.kernel import changes
from radd.modules.auth import service as auth
from radd.modules.automations.intake import suppressed as intake_suppressed
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.events import service as events
from radd.modules.items import service as items
from radd.modules.items.enums import ItemOrigin
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.snapshot import Snapshot

from . import planner
from .models import AlertItem, AlertReceiver
from .types import AlertAction, AlertEntity, AlertmanagerEvent, AlertTrigger

logger = logging.getLogger(__name__)

_TRIGGER_OF = {
    AlertAction.CREATE: AlertTrigger.FIRING,
    AlertAction.STILL_FIRING: AlertTrigger.REPEATED,
    AlertAction.RESOLVED: AlertTrigger.RESOLVED,
}


# --- the webhook ----------------------------------------------------------------


async def receiver_for_token(session: AsyncSession, token: str) -> AlertReceiver | None:
    """The ACTIVE receiver whose token this is — compared constant-time against
    each, so the answer does not depend on how early the match is."""
    supplied = (token or "").strip()
    if not supplied:
        return None
    found: AlertReceiver | None = None
    for receiver in (await session.execute(select(AlertReceiver).where(AlertReceiver.active))).scalars():
        if receiver.token and hmac.compare_digest(supplied, receiver.token):
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
    created = triggered = 0
    for plan in plans:
        if plan.action is AlertAction.CREATE:
            # Machine intake is not human intake (spec 119): a monitoring system
            # cannot be asked for repro steps, and refusing it is a 5xx it retries.
            with intake_suppressed(), items.creating_from(ItemOrigin.ALERT):
                item = await items.create_item(
                    session,
                    ItemCreate(project_id=receiver.project_id, title=plan.title, description=plan.description),
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
    return {"created": created, "triggered": triggered}


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


async def create_receiver(session: AsyncSession, data, *, actor_id: uuid.UUID | None = None) -> AlertReceiver:
    await _claim_seed(session)
    if (await session.execute(select(AlertReceiver).where(AlertReceiver.name == data.name))).scalar_one_or_none():
        raise ConflictError(AlertEntity.RECEIVER, data.name)
    receiver = AlertReceiver(name=data.name, token=data.token, project_id=data.project_id, active=data.active)
    session.add(receiver)
    await session.flush()
    await refresh_snapshot(session)
    await _emit(session, AlertmanagerEvent.RECEIVER_CREATED, receiver, actor_id)
    return receiver


async def update_receiver(session: AsyncSession, receiver_id: uuid.UUID, data, *, actor_id=None) -> AlertReceiver:
    receiver = await get_receiver(session, receiver_id)
    before = changes.snapshot(receiver, ("name", "token", "project_id", "active"))
    fields = data.model_dump(exclude_unset=True)
    if not fields.get("token"):
        fields.pop("token", None)  # empty on update keeps the stored token
    for key, value in fields.items():
        setattr(receiver, key, value)
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


# --- capability snapshot + env seed ------------------------------------------


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
            session.add(AlertReceiver(name="Alertmanager", token=token, project_id=project_id, active=True))
            logger.info("alertmanager: seeded one receiver from the environment")
        await session.commit()
        await refresh_snapshot(session)


async def _claim_seed(session: AsyncSession) -> bool:
    from sqlalchemy.dialects.postgresql import insert
    from .models import AlertSeed

    claimed = await session.scalar(insert(AlertSeed).values(key="environment")
                                   .on_conflict_do_nothing().returning(AlertSeed.key))
    return claimed is not None
