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


@router.post("/{entity_type}/{entity_id}/comments", response_model=CommentRead, status_code=201)
async def create_parent_comment(
    entity_type: str, entity_id: uuid.UUID, data: CommentCreate, session: Session, user: CurrentUser
) -> CommentRead:
    """Comment on anything that registered a parent binding (RADD-717).

    The item routes above stay as they are — they are in the SDK, the MCP tools
    and every existing client — and this is the general form the rest use, e.g.
    `POST /page/{id}/comments`.
    """
    return await service.create_comment(session, entity_id, data, actor=user, entity_type=entity_type)


@router.get("/{entity_type}/{entity_id}/comments", response_model=list[CommentRead])
async def list_parent_comments(
    entity_type: str, entity_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[CommentRead]:
    return await service.list_comments(session, entity_id, actor=user, entity_type=entity_type)


@router.patch("/comments/{comment_id}", response_model=CommentRead)
async def update_comment(
    comment_id: uuid.UUID, data: CommentUpdate, session: Session, user: CurrentUser
) -> CommentRead:
    return await service.update_comment(session, comment_id, data, actor=user)


@router.post("/comments/{comment_id}/resolve", response_model=CommentRead)
async def resolve_comment(
    comment_id: uuid.UUID, session: Session, user: CurrentUser
) -> CommentRead:
    """Close an inline thread (RADD-726). Resolve, never delete: a resolved
    comment leaves the rail and the highlight layer but stays readable."""
    return await service.set_resolved(session, comment_id, actor=user, resolved=True)


@router.post("/comments/{comment_id}/reopen", response_model=CommentRead)
async def reopen_comment(
    comment_id: uuid.UUID, session: Session, user: CurrentUser
) -> CommentRead:
    return await service.set_resolved(session, comment_id, actor=user, resolved=False)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(comment_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await service.delete_comment(session, comment_id, actor=user)
