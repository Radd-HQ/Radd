import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.deps import CurrentUser

from . import counts, service
from .schemas import (
    CardPresetCreate,
    CardPresetRead,
    CardPresetUpdate,
    ViewCountsRequest,
    ViewCreate,
    ViewRead,
    ViewSharingUpdate,
    ViewTransfer,
    ViewUpdate,
)

router = APIRouter(prefix="/views", tags=["views"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=ViewRead, status_code=201)
async def create_view(data: ViewCreate, session: Session, user: CurrentUser) -> ViewRead:
    return await service.create_view(session, data, actor=user)


@router.get("", response_model=list[ViewRead])
async def list_views(
    session: Session,
    user: CurrentUser,
    project_id: uuid.UUID | None = None,
) -> list[ViewRead]:
    return await service.list_views(session, actor=user, project_id=project_id)


_COUNTS_DOC = (
    "Batched membership counts for sidebar queue badges (spec 64): a compiled-SLQ "
    "SELECT count(*) per view, visibility-filtered exactly like the view read path — "
    "invisible/unknown ids are simply omitted. Quick filters are NOT applied (base "
    "membership count); archived items and projects without item.read don't count."
)


# Registered before the parameterized routes so the literal segment wins.
@router.post("/counts", response_model=dict[uuid.UUID, int], description=_COUNTS_DOC)
async def view_counts(
    data: ViewCountsRequest, session: Session, user: CurrentUser
) -> dict[uuid.UUID, int]:
    return await counts.view_counts(
        session, actor=user, view_ids=data.view_ids, extra_q=data.extra_q
    )


# --- card-layout preset library (spec 109) -----------------------------------
# Literal segments, registered before the parameterized /{view_id} routes so
# they win over uuid parsing (the /counts precedent). Applying a preset is
# client-side (PATCH the view's card_layout with a COPY) — no apply endpoint.


@router.get("/card-presets", response_model=list[CardPresetRead])
async def list_card_presets(session: Session, user: CurrentUser) -> list[CardPresetRead]:
    # Any member may browse (they apply these from the card designer) — the floor
    # is item.read in SOME project, not the global atom (RADD-788).
    if not await authz.readable_projects(session, user):
        return []
    return [
        CardPresetRead.model_validate(preset)
        for preset in await service.list_card_presets(session)
    ]


@router.post("/card-presets", response_model=CardPresetRead, status_code=201)
async def create_card_preset(
    data: CardPresetCreate, session: Session, user: CurrentUser
) -> CardPresetRead:
    await authz.require(session, user, Permission.CARD_PRESET_CREATE)
    return CardPresetRead.model_validate(await service.create_card_preset(session, data, user))


@router.patch("/card-presets/{preset_id}", response_model=CardPresetRead)
async def update_card_preset(
    preset_id: uuid.UUID, data: CardPresetUpdate, session: Session, user: CurrentUser
) -> CardPresetRead:
    await authz.require(session, user, Permission.CARD_PRESET_UPDATE)
    return CardPresetRead.model_validate(
        await service.update_card_preset(session, preset_id, data, user)
    )


@router.delete("/card-presets/{preset_id}", status_code=204)
async def delete_card_preset(preset_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await authz.require(session, user, Permission.CARD_PRESET_DELETE)
    await service.delete_card_preset(session, preset_id, user)


@router.patch("/{view_id}", response_model=ViewRead)
async def update_view(
    view_id: uuid.UUID, data: ViewUpdate, session: Session, user: CurrentUser
) -> ViewRead:
    return await service.update_view(session, view_id, data, actor=user)


_SHARING_DOC = (
    "Replace the view's FULL sharing state (spec 57): global_access (what every active user "
    "gets; null = not globally visible) + per-user/team grants at viewer|editor. Owner-only "
    "(legacy owner-less views: view.update); enabling global_access needs view.create."
)


@router.put("/{view_id}/sharing", response_model=ViewRead, description=_SHARING_DOC)
async def update_sharing(
    view_id: uuid.UUID, data: ViewSharingUpdate, session: Session, user: CurrentUser
) -> ViewRead:
    return await service.update_sharing(session, view_id, data, actor=user)


_TRANSFER_DOC = (
    "Reassign the view's owner (spec 57). Owner/co-owner only; the target must hold "
    "item.read in the view's scope (409 otherwise). The previous owner stays on as an "
    "editor grantee so a transfer never locks anyone out by accident."
)


@router.post("/{view_id}/transfer", response_model=ViewRead, description=_TRANSFER_DOC)
async def transfer_view(
    view_id: uuid.UUID, data: ViewTransfer, session: Session, user: CurrentUser
) -> ViewRead:
    return await service.transfer_ownership(session, view_id, data, actor=user)


_MEMBER_DOC = (
    "Curated membership (roadmap wave): pin/unpin an item to the view, idempotently. "
    "Edit-gated like any definition write (owner/editor; legacy owner-less views: "
    "view.update). Reads flow through the item dialect — `GET /items?q=roadmap = "
    '"<view id or name>"` returns the hydrated, RBAC-scoped member set.'
)


@router.put("/{view_id}/members/{item_id}", status_code=204, description=_MEMBER_DOC)
async def add_view_member(
    view_id: uuid.UUID, item_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    await service.add_member(session, view_id, item_id, actor=user)


@router.delete("/{view_id}/members/{item_id}", status_code=204, description=_MEMBER_DOC)
async def remove_view_member(
    view_id: uuid.UUID, item_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    await service.remove_member(session, view_id, item_id, actor=user)


@router.delete("/{view_id}", status_code=204)
async def delete_view(view_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await service.delete_view(session, view_id, actor=user)
