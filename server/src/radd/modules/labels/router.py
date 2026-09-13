import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.apitypes import TOTAL_COUNT_HEADER
from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import Actor, CurrentUser

from . import service
from .schemas import LabelCreate, LabelRead, LabelUpdate

router = APIRouter(prefix="/labels", tags=["labels"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=LabelRead, status_code=201)
async def create_label(data: LabelCreate, session: Session, user: CurrentUser) -> LabelRead:
    # Explicit label creation is admin territory; members create labels implicitly via items.
    await authz.require(session, user, authz.Permission.LABEL_CREATE)
    return LabelRead.model_validate(await service.create_label(session, data, actor_id=user.id))


@router.get("", response_model=list[LabelRead])
async def list_labels(
    response: Response,
    session: Session,
    user: Actor,
    q: str | None = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[LabelRead]:
    # RADD-816 (F6): the catalog read is a deliverable atom now — Baseline-
    # seeded, so day-one behaviour is the old member floor, but REVOCABLE.
    if not await authz.holds(session, user, authz.Permission.LABEL_READ):
        return []
    labels = await service.list_labels(session, q=q, limit=limit, offset=offset)
    if limit is not None:
        response.headers[TOTAL_COUNT_HEADER] = str(await service.count_labels(session, q=q))
    return [LabelRead.model_validate(label) for label in labels]


@router.patch("/{label_id}", response_model=LabelRead)
async def update_label(
    label_id: uuid.UUID, data: LabelUpdate, session: Session, user: CurrentUser
) -> LabelRead:
    """Rename/recolor a label (spec 87 — label.update had no endpoint before)."""
    await authz.require(session, user, authz.Permission.LABEL_UPDATE)
    label = await service.update_label(session, label_id, data, actor_id=user.id)
    return LabelRead.model_validate(label)


@router.delete("/{label_id}", status_code=204)
async def delete_label(label_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    """Hard-delete a label; it detaches from every item that carried it (spec 87)."""
    await authz.require(session, user, authz.Permission.LABEL_DELETE)
    await service.delete_label(session, label_id, actor_id=user.id)
