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

from . import parsing, service
from .types import ForgejoEventKind

logger = logging.getLogger(__name__)

router = APIRouter(tags=["forgejo"])

Session = Annotated[AsyncSession, Depends(get_session)]


# Signature verification moved to service.verify_signature in spec 111 — the
# receiver no longer knows which secret to use until it has resolved the
# connection, so the check belongs next to that lookup. Re-exported because
# tests/test_connectors.py imports it from here.
verify_signature = service.verify_signature


@router.post("/integrations/forgejo")
async def forgejo_webhook(
    request: Request,
    session: Session,
    x_forgejo_signature: Annotated[str, Header()] = "",
    x_gitea_signature: Annotated[str, Header()] = "",
    x_forgejo_event: Annotated[str, Header()] = "",
    x_gitea_event: Annotated[str, Header()] = "",
) -> dict[str, int]:
    """Forgejo/Gitea webhook receiver (specs 47, 111). Auth = HMAC-SHA256 of the
    RAW body vs the signature header, checked against the secret of the CONNECTION
    this payload came from; the write path is the vcs connector seam, attributed
    to the system actor. Mirrors the gitlab connector (spec 31)."""
    raw_body = await request.body()
    signature = x_forgejo_signature or x_gitea_signature
    try:
        payload = json.loads(raw_body)
    except ValueError:
        raise ForbiddenError("forgejo webhook body is not JSON") from None

    resolved = await service.resolve_for_payload(session, payload, raw_body, signature)
    if resolved is None:
        # No active connection signed this. Covers three cases with one answer:
        # nothing configured, the wrong secret, and an inactive host.
        raise ForbiddenError("bad forgejo webhook signature")
    _connection, _repo = resolved

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
