"""The unauthenticated GitHub webhook receiver (RADD-1129).

Auth = HMAC-SHA256 of the RAW body against `X-Hub-Signature-256`, verified with
the secret of the CONNECTION this payload came from. The write path is the vcs
connector seam, attributed to the system actor. Mirrors the Forgejo receiver
(specs 47, 111) with GitHub's event names and payload shapes.
"""

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth import service as auth
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemUpdate
from radd.modules.projects import service as projects_service
from radd.modules.releases import pipeline
from radd.modules.vcs import service as vcs
from radd.modules.vcs.types import VcsProvider

from . import parsing, service
from .types import GithubEventKind

logger = logging.getLogger(__name__)

router = APIRouter(tags=["github"])

Session = Annotated[AsyncSession, Depends(get_session)]

verify_signature = service.verify_signature


@router.post("/integrations/github")
async def github_webhook(
    request: Request,
    session: Session,
    x_hub_signature_256: Annotated[str, Header()] = "",
    x_github_event: Annotated[str, Header()] = "",
    x_github_delivery: Annotated[str, Header()] = "",
) -> dict[str, int]:
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except ValueError:
        raise ForbiddenError("github webhook body is not JSON") from None

    resolved = await service.resolve_for_payload(session, payload, raw_body, x_hub_signature_256)
    if resolved is None:
        # Nothing configured, the wrong secret, or an inactive host: one answer.
        raise ForbiddenError("bad github webhook signature")
    _connection, repo = resolved

    kind = x_github_event
    merged = False
    if kind == GithubEventKind.PING:
        # GitHub sends one when the hook is created; answering 200 is what makes
        # the "recent deliveries" panel show a green tick.
        return {"linked": 0, "transitioned": 0}
    if kind == GithubEventKind.PUSH:
        planned = parsing.plan_push(payload)
    elif kind == GithubEventKind.PULL_REQUEST:
        planned, merged = parsing.plan_pull_request(payload)
    elif kind in (GithubEventKind.CHECK_RUN, GithubEventKind.CHECK_SUITE, GithubEventKind.WORKFLOW_RUN):
        return await _handle_ci(session, kind, payload)
    elif kind == GithubEventKind.RELEASE:
        return await _handle_release(session, payload, repo)
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
            provider=VcsProvider.GITHUB,
            ref_type=plan.ref_type,
            external_id=plan.external_id,
            title=plan.title,
            url=plan.url,
            status=plan.status,
            actor_id=SYSTEM_ACTOR_ID,
        )
        linked += 1

    transitioned = 0
    if merged and referenced:
        transitioned = await _transition_merged(session, list(referenced.values()))
    logger.debug("github delivery %s: %s linked, %s transitioned", x_github_delivery, linked, transitioned)
    return {"linked": linked, "transitioned": transitioned}


async def _handle_ci(session: AsyncSession, kind: str, payload: dict) -> dict[str, int]:
    update = parsing.plan_ci(kind, payload)
    if update is None:
        return {"linked": 0, "transitioned": 0}
    stamped = await vcs.set_ci_state(
        session,
        provider=VcsProvider.GITHUB,
        external_ids=list(update.external_ids),
        ci_state=update.state,
        ci_url=update.url,
    )
    return {"linked": stamped, "transitioned": 0}


async def _handle_release(session: AsyncSession, payload: dict, repo) -> dict[str, int]:
    """`release` webhook (spec 112). Only `published` ships anything — a draft,
    an edit or a deletion must not close work. A repository with no project
    has nowhere to create the version, so it is a no-op."""
    action = str(payload.get("action") or "")
    release_payload = payload.get("release") or {}
    version = parsing.version_from_tag(str(release_payload.get("tag_name") or ""))
    if (
        action != "published"
        or not version
        or release_payload.get("draft")
        or repo is None
        or repo.project_id is None
    ):
        return {"linked": 0, "transitioned": 0}
    project = await projects_service.get_project(session, repo.project_id)
    _release, moved = await pipeline.on_release_published(
        session,
        project,
        version=version,
        name=str(release_payload.get("name") or version),
        notes=str(release_payload.get("body") or ""),
    )
    return {"linked": 0, "transitioned": moved}


async def _transition_merged(session: AsyncSession, merged_items: list[Any]) -> int:
    """Move each referenced item to its project's WAITING-for-release state
    (spec 112): a merged PR means the work is done, not that it has shipped."""
    actor = await auth.get_user(session, SYSTEM_ACTOR_ID)
    count = 0
    for item in merged_items:
        project = await projects_service.get_project(session, item.project_id)
        target_id = await pipeline.waiting_state_id(session, project)
        if target_id is None or item.state_id == target_id:
            continue
        try:
            await items.update_item(session, item.id, ItemUpdate(state_id=target_id), actor)
            count += 1
        except Exception:
            logger.exception("github: merge transition failed for item %s", item.id)
    return count
