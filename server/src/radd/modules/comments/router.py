import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth.deps import CurrentUser

from . import service
from .schemas import CommentCreate, CommentRead, CommentUpdate

# No prefix: routes span two roots (/items/{id}/comments for the collection,
# /comments/{id} for direct addressing).
router = APIRouter(tags=["comments"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/items/{item_id}/comments", response_model=CommentRead, status_code=201)
async def create_comment(
    item_id: uuid.UUID, data: CommentCreate, session: Session, user: CurrentUser
) -> CommentRead:
    return await service.create_comment(session, item_id, data, actor=user)


@router.get("/items/{item_id}/comments", response_model=list[CommentRead])
async def list_comments(
    item_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[CommentRead]:
    return await service.list_comments(session, item_id, actor=user)


@router.patch("/comments/{comment_id}", response_model=CommentRead)
async def update_comment(
    comment_id: uuid.UUID, data: CommentUpdate, session: Session, user: CurrentUser
) -> CommentRead:
    return await service.update_comment(session, comment_id, data, actor=user)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(comment_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await service.delete_comment(session, comment_id, actor=user)
