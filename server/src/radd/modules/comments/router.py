import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.tasklists import TaskToggle
from radd.modules.auth.deps import Actor, CurrentUser
from radd.modules.auth.throttle import WriteBucket, check_write

from radd.modules.auth import authz
from radd.modules.projects import service as projects_service

from . import resolution, service, threads
from .schemas import (
    CommentCreate, CommentLocation, CommentPage, CommentRead, CommentReplyCreate, CommentUpdate, ThreadResolutionPolicy,
)
from .types import CommentSlice

# No prefix: routes span two roots (/items/{id}/comments for the collection,
# /comments/{id} for direct addressing).
router = APIRouter(tags=["comments"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/comments/{comment_id}/replies", response_model=CommentPage)
async def comment_replies(comment_id: uuid.UUID, session: Session, user: Actor,
    limit: int = Query(50, ge=1, le=200), before: str | None = Query(None, max_length=256),
) -> CommentPage:
    return await threads.reply_page(session, comment_id, user, limit=limit, before=before)


@router.post("/comments/{comment_id}/replies", response_model=CommentRead, status_code=201)
async def reply_to_comment(comment_id: uuid.UUID, data: CommentReplyCreate, session: Session, user: CurrentUser) -> CommentRead:
    check_write(user, WriteBucket.COMMENT_CREATE)
    return await threads.create_reply(session, comment_id, data, user)


@router.post("/items/{item_id}/comments", response_model=CommentRead, status_code=201)
async def create_comment(
    item_id: uuid.UUID, data: CommentCreate, session: Session, user: CurrentUser
) -> CommentRead:
    check_write(user, WriteBucket.COMMENT_CREATE)
    return await service.create_comment(session, item_id, data, actor=user)


@router.get("/items/{item_id}/comments", response_model=list[CommentRead])
async def list_comments(
    item_id: uuid.UUID, session: Session, user: Actor
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
    check_write(user, WriteBucket.COMMENT_CREATE)
    return await service.create_comment(session, entity_id, data, actor=user, entity_type=entity_type)


@router.get("/{entity_type}/{entity_id}/comments", response_model=list[CommentRead])
async def list_parent_comments(
    entity_type: str, entity_id: uuid.UUID, session: Session, user: Actor
) -> list[CommentRead]:
    return await service.list_comments(session, entity_id, actor=user, entity_type=entity_type)


@router.patch("/comments/{comment_id}", response_model=CommentRead)
async def update_comment(
    comment_id: uuid.UUID, data: CommentUpdate, session: Session, user: CurrentUser
) -> CommentRead:
    return await service.update_comment(session, comment_id, data, actor=user)


@router.get("/comments/{comment_id}/locate", response_model=CommentLocation)
async def locate_comment(comment_id: uuid.UUID, session: Session, user: Actor) -> CommentLocation:
    """Where a linked comment lives (RADD-1297): its thread root and parent.
    404 for a comment this reader cannot see — never a hint that it exists."""
    return await service.locate(session, comment_id, user)


@router.post("/comments/{comment_id}/tasks", response_model=CommentRead)
async def toggle_comment_task(
    comment_id: uuid.UUID, data: TaskToggle, session: Session, user: CurrentUser
) -> CommentRead:
    """Tick or untick one checklist box without editing the comment (RADD-1296)."""
    return await service.toggle_task(session, comment_id, data, actor=user)


@router.post("/comments/{comment_id}/resolve", response_model=CommentRead)
async def resolve_comment(
    comment_id: uuid.UUID, session: Session, user: CurrentUser
) -> CommentRead:
    """Resolve a discussion or inline annotation while preserving its replies."""
    return await service.set_resolved(session, comment_id, actor=user, resolved=True)


@router.post("/comments/{comment_id}/reopen", response_model=CommentRead)
async def reopen_comment(
    comment_id: uuid.UUID, session: Session, user: CurrentUser
) -> CommentRead:
    return await service.set_resolved(session, comment_id, actor=user, resolved=False)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(comment_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await service.delete_comment(session, comment_id, actor=user)


@router.get("/items/{entity_id}/comments/feed", response_model=CommentPage)
async def item_comment_page(
    entity_id: uuid.UUID, session: Session, user: Actor,
    limit: int = Query(50, ge=1, le=200), before: str | None = Query(None, max_length=256),
    section: CommentSlice = CommentSlice.ALL,
    unresolved: bool = Query(False, description="Only resolvable threads that are still unresolved."),
    through: uuid.UUID | None = Query(None, description="Widen the newest window to include this comment (RADD-1297)."),
) -> CommentPage:
    return await service.comment_page(
        session, entity_id, user, limit=limit, before=before, section=section, unresolved=unresolved,
        through=through,
    )


@router.get("/{entity_type}/{entity_id}/comments/feed", response_model=CommentPage)
async def parent_comment_page(
    entity_type: str, entity_id: uuid.UUID, session: Session, user: Actor,
    limit: int = Query(50, ge=1, le=200), before: str | None = Query(None, max_length=256),
    section: CommentSlice = CommentSlice.ALL,
    unresolved: bool = Query(False, description="Only resolvable threads that are still unresolved."),
    through: uuid.UUID | None = Query(None, description="Widen the newest window to include this comment (RADD-1297)."),
) -> CommentPage:
    return await service.comment_page(
        session, entity_id, user, entity_type, limit=limit, before=before, section=section,
        unresolved=unresolved, through=through,
    )


# --- RADD-1283: who may resolve a thread, per project and issue type ------------


@router.get("/projects/{project_id}/thread-resolution", response_model=ThreadResolutionPolicy)
async def get_thread_resolution(project_id: uuid.UUID, session: Session, user: CurrentUser) -> ThreadResolutionPolicy:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.PROJECT_MANAGE, project=project)
    return await resolution.get_policy(session, project_id)


@router.put("/projects/{project_id}/thread-resolution", response_model=ThreadResolutionPolicy)
async def put_thread_resolution(
    project_id: uuid.UUID, data: ThreadResolutionPolicy, session: Session, user: CurrentUser
) -> ThreadResolutionPolicy:
    """Replace the project's rules: a default plus per-issue-type overrides."""
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.PROJECT_MANAGE, project=project)
    return await resolution.set_policy(session, project_id, data, user)

