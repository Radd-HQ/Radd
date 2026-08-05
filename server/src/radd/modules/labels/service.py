import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.events import service as events

from .models import Label
from .schemas import LabelCreate, LabelUpdate
from .types import LabelEntity, LabelEvent


async def create_label(
    session: AsyncSession, data: LabelCreate, actor_id: uuid.UUID | None = None
) -> Label:
    existing = await session.scalar(select(Label.id).where(Label.name == data.name))
    if existing:
        raise ConflictError(LabelEntity.LABEL, data.name)
    return await _create(session, data.name, data.color, actor_id=actor_id)


async def list_labels(
    session: AsyncSession,
    *,
    q: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[Label]:
    stmt = select(Label).order_by(Label.name)
    if q:
        stmt = stmt.where(Label.name.ilike(ilike_term(q)))
    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)
    return list((await session.execute(stmt)).scalars())


async def count_labels(session: AsyncSession, *, q: str | None = None) -> int:
    stmt = select(func.count()).select_from(Label)
    if q:
        stmt = stmt.where(Label.name.ilike(ilike_term(q)))
    return (await session.execute(stmt)).scalar_one()


async def get_label(session: AsyncSession, label_id: uuid.UUID) -> Label:
    label = await session.get(Label, label_id)
    if label is None:
        raise NotFoundError(LabelEntity.LABEL, label_id)
    return label


async def update_label(
    session: AsyncSession, label_id: uuid.UUID, data: LabelUpdate, actor_id: uuid.UUID | None = None
) -> Label:
    """Rename/recolor (spec 87 — the label.update atom had no endpoint until now)."""
    label = await get_label(session, label_id)
    if data.name is not None and data.name != label.name:
        clash = await session.scalar(
            select(Label.id).where(Label.name == data.name, Label.id != label.id)
        )
        if clash:
            raise ConflictError(LabelEntity.LABEL, data.name)
        label.name = data.name
    if data.color is not None:
        label.color = data.color
    await session.flush()
    await events.emit(
        session,
        event_type=LabelEvent.UPDATED,
        entity_type=LabelEntity.LABEL,
        entity_id=label.id,
        actor_id=actor_id,
        payload={"name": label.name, "color": label.color},
    )
    return label


async def delete_label(
    session: AsyncSession, label_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    """Hard-delete (spec 87). `item_labels` CASCADEs, so this detaches the label
    from every item that carried it. The label module deliberately does not count
    those items first — that would mean reading the items module's tables; the
    emitted event is the seam anyone needing the detail subscribes to."""
    label = await get_label(session, label_id)
    await events.emit(
        session,
        event_type=LabelEvent.DELETED,
        entity_type=LabelEntity.LABEL,
        entity_id=label.id,
        actor_id=actor_id,
        payload={"name": label.name},
    )
    await session.delete(label)
    await session.flush()


async def resolve_labels(
    session: AsyncSession,
    names: Sequence[str],
    actor_id: uuid.UUID | None = None,
) -> list[Label]:
    """Map names to labels, auto-creating unknown ones — automation writes labels freely."""
    cleaned: list[str] = []
    for name in (n.strip() for n in names):
        if name and name not in cleaned:
            cleaned.append(name)
    if not cleaned:
        return []
    result = await session.execute(select(Label).where(Label.name.in_(cleaned)))
    by_name = {label.name: label for label in result.scalars()}
    for name in cleaned:
        if name not in by_name:
            by_name[name] = await _create(session, name, color=None, actor_id=actor_id)
    return [by_name[name] for name in cleaned]


async def labels_by_ids(session: AsyncSession, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Label]:
    result = await session.execute(select(Label).where(Label.id.in_(set(ids))))
    return {label.id: label for label in result.scalars()}


async def _create(
    session: AsyncSession,
    name: str,
    color: str | None,
    actor_id: uuid.UUID | None = None,
) -> Label:
    label = Label(name=name, color=color)
    session.add(label)
    await session.flush()
    await events.emit(
        session,
        event_type=LabelEvent.CREATED,
        entity_type=LabelEntity.LABEL,
        entity_id=label.id,
        actor_id=actor_id,
        payload={"name": label.name},
    )
    return label
