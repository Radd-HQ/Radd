"""The unauthenticated GitLab webhook receiver (spec 31, rebuilt RADD-1253).

Auth = the hook's secret token, sent back verbatim as `X-Gitlab-Token`, compared
constant-time against the secret of the CONNECTION this payload's project
belongs to. The write path is the vcs connector seam, attributed to the system
actor. Mirrors the Forgejo (specs 47/111) and GitHub (RADD-1129) receivers with
GitLab's event names and payload shapes.
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

from . import parsing, service, timelogs
from .types import GitlabEventKind

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gitlab"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _kind(payload: dict, header: str) -> str:
    """`object_kind` is authoritative; the header ("Merge Request Hook") is a
    display name and only a fallback when the body lacks the field."""
    kind = str(payload.get("object_kind") or "").strip()
    if kind:
        return kind
    return header.lower().replace(" hook", "").replace(" ", "_")


@router.post("/integrations/gitlab")
async def gitlab_webhook(
    request: Request,
    session: Session,
    x_gitlab_token: Annotated[str, Header()] = "",
    x_gitlab_event: Annotated[str, Header()] = "",
    x_gitlab_event_uuid: Annotated[str, Header()] = "",
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except ValueError:
        raise ForbiddenError("gitlab webhook body is not JSON") from None
    if not isinstance(payload, dict):
        raise ForbiddenError("gitlab webhook body is not an object")

    resolved = await service.resolve_for_payload(session, payload, x_gitlab_token)
    if resolved is None:
        # Nothing configured, the wrong token, or an inactive host: one answer.
        raise ForbiddenError("bad gitlab webhook token")
    connection, repo = resolved

    kind = _kind(payload, x_gitlab_event)
    result: dict[str, Any] = {"linked": 0, "transitioned": 0}
    merged = False
    if kind == GitlabEventKind.PUSH:
        planned = parsing.plan_push(payload)
    elif kind == GitlabEventKind.MERGE_REQUEST:
        planned, merged = parsing.plan_merge_request(payload)
    else:
        # tag_push / pipeline / deployment / release: RADD-1255 and RADD-1256.
        return result

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
        result["linked"] += 1

    if merged and referenced:
        result["transitioned"] = await _transition_merged(session, list(referenced.values()))

    # RADD-1259: time added or removed on the MR → fetch the entries and mirror
    # them. Needs a token; a hook-only connection simply reports nothing.
    if kind == GitlabEventKind.MERGE_REQUEST and connection.api_token and parsing.time_spent_changed(payload):
        attributes = payload.get("object_attributes") or {}
        try:
            report = await timelogs.reconcile_merge_request(
                session,
                connection,
                repo,
                project_path=parsing.project_path(payload),
                iid=attributes.get("iid", ""),
                title=str(attributes.get("title") or ""),
                source_branch=str(attributes.get("source_branch") or ""),
                description=str(attributes.get("description") or ""),
            )
            result["worklogs"] = report.as_dict()
        except Exception:  # the link half already landed; time is best-effort
            logger.exception("gitlab: timelog mirror failed for %s !%s", parsing.project_path(payload), attributes.get("iid"))
            result["worklogs"] = {"error": "timelog fetch failed; see the server log"}

    logger.debug("gitlab delivery %s: %s", x_gitlab_event_uuid, result)
    return result


async def _transition_merged(session: AsyncSession, merged_items: list[Any]) -> int:
    """Move each referenced item to its project's WAITING-for-release state
    (spec 112): a merged MR means the work is done, not that it has shipped. A
    project without the pipeline configured has no waiting state — a logged skip."""
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
            logger.exception("gitlab: merge transition failed for item %s", item.id)
    return count
