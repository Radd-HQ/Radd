import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth.deps import CurrentUser

from . import service
from .schemas import (
    ApprovalRequestCreate,
    ApprovalRequestRead,
    ApprovalVoteCreate,
    ItemApprovalsRead,
    PendingApprovalRead,
    VoteResult,
)

router = APIRouter(tags=["approvals"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/items/{item_id}/approvals", response_model=ItemApprovalsRead)
async def item_approvals(
    item_id: uuid.UUID, session: Session, user: CurrentUser
) -> ItemApprovalsRead:
    """Live requests + history + server-computed requestable targets (item.read)."""
    return await service.item_approvals(session, item_id, user)


@router.post("/items/{item_id}/approvals", response_model=ApprovalRequestRead, status_code=201)
async def request_approval(
    item_id: uuid.UUID, data: ApprovalRequestCreate, session: Session, user: CurrentUser
) -> ApprovalRequestRead:
    """Open a request (item.update) — 409 without a matching require_approval
    rule for (current state -> to_state) or with a live request already open."""
    return await service.create_request(session, item_id, data, user)


@router.post("/approvals/{request_id}/vote", response_model=VoteResult)
async def vote(
    request_id: uuid.UUID, data: ApprovalVoteCreate, session: Session, user: CurrentUser
) -> VoteResult:
    """Eligible approvers only (403); revote replaces while pending. The deciding
    approve AUTO-APPLIES the move — banked-unlock guard errors ride the response."""
    return await service.vote(session, request_id, data, user)


@router.delete("/approvals/{request_id}", status_code=204)
async def cancel(request_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    """Requester or project.manage withdraws a live request -> canceled."""
    await service.cancel_request(session, request_id, user)


@router.get("/approvals/pending", response_model=list[PendingApprovalRead])
async def pending(session: Session, user: CurrentUser) -> list[PendingApprovalRead]:
    """Requests awaiting MY verdict (eligibility resolved live) — the My Work card."""
    return await service.pending_for_user(session, user)
