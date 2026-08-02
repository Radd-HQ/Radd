import hashlib
import hmac
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
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
from .types import ForgejoEventKind

logger = logging.getLogger(__name__)

router = APIRouter(tags=["forgejo"])

Session = Annotated[AsyncSession, Depends(get_session)]


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Constant-time check of the hex HMAC-SHA256 the X-Forgejo-Signature /
    X-Gitea-Signature header carries against the shared secret."""
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


@router.post("/integrations/forgejo")
async def forgejo_webhook(
    request: Request,
    session: Session,
    x_forgejo_signature: Annotated[str, Header()] = "",
    x_gitea_signature: Annotated[str, Header()] = "",
    x_forgejo_event: Annotated[str, Header()] = "",
    x_gitea_event: Annotated[str, Header()] = "",
) -> dict[str, int]:
    """Forgejo/Gitea webhook receiver (spec 47). Auth = HMAC-SHA256 of the RAW
    body vs the signature header; the write path is the vcs connector seam,
    attributed to the system actor. Mirrors the gitlab connector (spec 31)."""
    secret = settings.forgejo_webhook_secret
    if not secret:
        raise ForbiddenError("forgejo connector is disabled (RADD_FORGEJO_WEBHOOK_SECRET unset)")
    raw_body = await request.body()
    signature = x_forgejo_signature or x_gitea_signature
    if not verify_signature(raw_body, signature, secret):
        raise ForbiddenError("bad forgejo webhook signature")

    payload = json.loads(raw_body)
    kind = x_forgejo_event or x_gitea_event
    merged = False
    if kind == ForgejoEventKind.PUSH:
        planned = parsing.plan_push(payload)
    elif kind == ForgejoEventKind.PULL_REQUEST:
        planned, merged = parsing.plan_pull_request(payload)
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
            provider=VcsProvider.FORGEJO,
            ref_type=plan.ref_type,
            external_id=plan.external_id,
            title=plan.title,
            url=plan.url,
            status=plan.status,
            actor_id=SYSTEM_ACTOR_ID,
        )
        linked += 1

    transitioned = 0
    if merged and settings.forgejo_merge_transition_state and referenced:
        transitioned = await _transition_merged(session, list(referenced.values()))
    return {"linked": linked, "transitioned": transitioned}


async def _transition_merged(session: AsyncSession, merged_items: list[Any]) -> int:
    """Move each referenced item to its project's configured post-merge state
    (name match; missing/already-there = skip) as the system actor."""
    target_name = settings.forgejo_merge_transition_state
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
            logger.exception("forgejo: merge transition failed for item %s", item.id)
    return count
