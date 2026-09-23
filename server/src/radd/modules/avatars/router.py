import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import NotFoundError
from radd.modules.auth.deps import Actor, CurrentUser
from radd.modules.auth.models import User
from radd.modules.auth.principals import require_account_session
from pydantic import BaseModel

from . import service

router = APIRouter(tags=["avatars"])


class AvatarRead(BaseModel):
    """What the picture resolves to now — uploaded, the IdP's, or none."""

    avatar_url: str | None

Session = Annotated[AsyncSession, Depends(get_session)]


@router.put("/auth/me/avatar", response_model=AvatarRead)
async def upload_avatar(
    session: Session, user: CurrentUser, file: UploadFile = File(...)
) -> AvatarRead:
    """Upload your picture (RADD-1295). Normalised to a 256px square WebP; the
    original is not kept. Replaces any earlier upload."""
    require_account_session(user)
    await service.upload(session, user, file)
    return AvatarRead(avatar_url=user.avatar_url)


@router.delete("/auth/me/avatar", response_model=AvatarRead)
async def remove_avatar(session: Session, user: CurrentUser) -> AvatarRead:
    """Back to your sign-in provider's picture, or your colour/emoji."""
    require_account_session(user)
    await service.remove(session, user)
    return AvatarRead(avatar_url=user.avatar_url)


@router.get("/users/{user_id}/avatar", responses={200: {"content": {"image/webp": {}}}})
async def get_avatar(user_id: uuid.UUID, session: Session, actor: Actor) -> Response:
    """A person's uploaded picture. Anyone who can see the person's name can
    see their face — a public project's visitors included — and the URL carries
    the picture's version, so it is cached for good."""
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("user", user_id)
    return Response(
        await service.picture(session, user),
        media_type=service.AVATAR_CONTENT_TYPE,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
