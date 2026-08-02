import hmac
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth import service as auth
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemUpdate
from radd.modules.vcs import service as vcs
from radd.modules.vcs.types import VcsProvider
from radd.modules.workflow import service as workflow

from . import parsing

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gitlab"])

Session = Annotated[AsyncSession, Depends(get_session)]

# GitLab webhook payload kinds this connector handles.
_PUSH = "push"
_MERGE_REQUEST = "merge_request"


@router.post("/integrations/gitlab")
async def gitlab_webhook(
    payload: dict[str, Any],
    session: Session,
    x_gitlab_token: Annotated[str, Header()] = "",
) -> dict[str, int]:
    """GitLab webhook receiver (spec 31). Auth = the shared secret header; the
    write path is the vcs connector seam, attributed to the system actor."""
    secret = settings.gitlab_webhook_secret
    if not secret:
        raise ForbiddenError("gitlab connector is disabled (RADD_GITLAB_WEBHOOK_SECRET unset)")
    if not hmac.compare_digest(x_gitlab_token, secret):
        raise ForbiddenError("bad gitlab webhook token")

    kind = payload.get("object_kind", "")
    merged = False
    if kind == _PUSH:
        planned = parsing.plan_push(payload)
    elif kind == _MERGE_REQUEST:
        planned, merged = parsing.plan_merge_request(payload)
    else:
        return {"linked": 0, "transitioned": 0}

    linked = 0
    referenced: dict[str, Any] = {}  # key -> WorkItem (for the merge transition)
    for plan in planned:
        item = referenced.get(plan.item_key)
        if item is None:
            item = await items.find_item_by_key(session, plan.item_key)
            if item is None:
                continue  # references an unknown key — skip silently
            referenced[plan.item_key] = item
        await vcs.upsert_vcs_link(
            session,
            item.id,
            provider=VcsProvider.GITLAB,
            ref_type=plan.ref_type,
            external_id=plan.external_id,
            title=plan.title,
            url=plan.url,
            status=plan.status,
            actor_id=SYSTEM_ACTOR_ID,
        )
        linked += 1

    transitioned = 0
    if merged and settings.gitlab_merge_transition_state and referenced:
        transitioned = await _transition_merged(session, list(referenced.values()))
    return {"linked": linked, "transitioned": transitioned}


async def _transition_merged(session: AsyncSession, merged_items: list[Any]) -> int:
    """Move each referenced item to its project's configured post-merge state
    (name match; missing/already-there = skip) as the system actor."""
    target_name = settings.gitlab_merge_transition_state
    actor = await auth.get_user(session, SYSTEM_ACTOR_ID)
    count = 0
    for item in merged_items:
        states = await workflow.list_states(session, item.project_id)
        target = next((state for state in states if state.name == target_name), None)
        if target is None or item.state_id == target.id:
            continue
        try:
            await items.update_item(session, item.id, ItemUpdate(state_id=target.id), actor)
            count += 1
        except Exception:
            logger.exception("gitlab: merge transition failed for item %s", item.id)
    return count
