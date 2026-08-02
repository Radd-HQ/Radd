"""The plugin's OWN API endpoint — this is how server-side plugin logic reaches the UI.

`GET /api/v1/notes/stats` returns a server-computed aggregate; the Notes page widget fetches it.
Built entirely against the public SDK: `get_session` (the kernel session) + `CurrentUser` (requires
an authenticated actor, so the endpoint is guarded). Mounted via `routers=(router,)` in the manifest;
plugin routers mount before the auto-generated entity CRUD, so `/notes/stats` resolves to this, not
to `GET /notes/{id}`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from radd.sdk import CurrentUser, get_session

from . import service

Session = Annotated[AsyncSession, Depends(get_session)]

router = APIRouter(prefix="/notes", tags=["acme-notes"])


class NotesStats(BaseModel):
    total: int
    items_with_notes: int
    top_item_id: str | None
    top_item_count: int


@router.get("/stats", response_model=NotesStats)
async def notes_stats(
    session: Session,
    user: CurrentUser,  # authenticated actor required
    project_id: uuid.UUID | None = None,
) -> NotesStats:
    return NotesStats(**await service.notes_stats(session, project_id))


class RecentNote(BaseModel):
    id: str
    item_id: str | None
    body: str
    created_at: str | None


@router.get("/recent", response_model=list[RecentNote])
async def recent_notes(session: Session, user: CurrentUser, limit: int = 10) -> list[RecentNote]:
    return [RecentNote(**n) for n in await service.recent_notes(session, min(max(limit, 1), 50))]
