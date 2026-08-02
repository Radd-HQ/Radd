import json
import logging
from types import SimpleNamespace
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
from radd.modules.projects import service as projects_service
from radd.modules.releases import pipeline
from radd.modules.vcs import service as vcs
from radd.modules.vcs.types import VcsProvider
from radd.modules.workflow import service as workflow

from . import parsing, service
from .types import CiState, ForgejoEventKind

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
    elif kind in (ForgejoEventKind.WORKFLOW_RUN, ForgejoEventKind.WORKFLOW_JOB):
        # Spec 111: CI state for a ref. Forgejo Actions is not on every host, so
        # a payload we cannot read is a no-op rather than an error.
        return await _handle_workflow_run(session, payload)
    elif kind == ForgejoEventKind.RELEASE:
        # Spec 112: a published version records the release and ships everything
        # waiting for it. Needs the repository's project — a tag in an unmapped
        # repository has no project to create a version in, so it is a no-op.
        return await _handle_release(session, payload, _repo)
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
    if merged and referenced:
        transitioned = await _transition_merged(session, list(referenced.values()))
    return {"linked": linked, "transitioned": transitioned}


_CI_STATES = {
    "success": CiState.SUCCESS,
    "failure": CiState.FAILURE,
    "cancelled": CiState.CANCELLED,
    "in_progress": CiState.RUNNING,
    "queued": CiState.RUNNING,
    "waiting": CiState.RUNNING,
}


async def _handle_workflow_run(session: AsyncSession, payload: dict) -> dict[str, int]:
    run = payload.get("workflow_run") or payload.get("workflow_job") or {}
    repository = (payload.get("repository") or {}).get("full_name") or ""
    branch = str(run.get("head_branch") or "")
    sha = str(run.get("head_sha") or "")
    status = str(run.get("conclusion") or run.get("status") or "")
    if not repository or not (branch or sha):
        return {"linked": 0, "transitioned": 0}
    ci_state = _CI_STATES.get(status, CiState.UNKNOWN)
    external_ids = []
    if branch:
        external_ids.append(f"branch:{repository}:{branch}")
    if sha:
        external_ids.append(f"commit:{repository}:{sha}")
    stamped = await vcs.set_ci_state(
        session,
        provider=VcsProvider.FORGEJO,
        external_ids=external_ids,
        ci_state=str(ci_state),
        ci_url=str(run.get("html_url") or ""),
    )
    return {"linked": stamped, "transitioned": 0}


async def _handle_release(
    session: AsyncSession, payload: dict, repo
) -> dict[str, int]:
    """`release` webhook (spec 112). Only the `published` action ships anything —
    a draft or a deletion must not close work."""
    action = str(payload.get("action") or "")
    release_payload = payload.get("release") or {}
    version = str(release_payload.get("tag_name") or "").strip()
    if action != "published" or not version or repo is None or repo.project_id is None:
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
    """Move each referenced item to the project's WAITING-for-release state (spec
    112): a merged PR means the work is done, not that it has shipped.

    Falls back to the spec-47 env state name for a project that has not set the
    pipeline up, so an existing deployment keeps its old behaviour.
    """
    actor = await auth.get_user(session, SYSTEM_ACTOR_ID)
    count = 0
    for item in merged_items:
        project = await projects_service.get_project(session, item.project_id)
        target_id = await pipeline.waiting_state_id(session, project)
        if target_id is None:
            states = await workflow.list_states(session, item.project_id)
            fallback = next(
                (s for s in states if s.name == settings.forgejo_merge_transition_state), None
            )
            target_id = fallback.id if fallback else None
        target = SimpleNamespace(id=target_id) if target_id else None
        if target is None or item.state_id == target.id:
            continue
        try:
            await items.update_item(session, item.id, ItemUpdate(state_id=target.id), actor)
            count += 1
        except Exception:
            logger.exception("forgejo: merge transition failed for item %s", item.id)
    return count
