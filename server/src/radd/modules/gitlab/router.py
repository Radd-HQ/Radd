"""The unauthenticated GitLab webhook receiver (spec 31, rebuilt RADD-1253).

Auth = the hook's secret token, sent back verbatim as `X-Gitlab-Token`, compared
constant-time against the secret of the CONNECTION this payload's project
belongs to. The write path is the vcs connector seam, attributed to the system
actor. Mirrors the Forgejo (specs 47/111) and GitHub (RADD-1129) receivers with
GitLab's event names and payload shapes.

RADD-1309: the receiver links refs, mirrors MR time, and fires GitLab's own
triggers (`GitlabTrigger`). It changes nothing else — a merged MR used to move
every issue it named to waiting-for-release with no switch; that is now an
automation someone builds on "GitLab: merge request merged".
"""

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.vcs import receiving, triggers
from radd.modules.vcs.types import VcsProvider

from . import parsing, service, timelogs
from .types import GitlabEntity, GitlabEventKind, GitlabTrigger, ReleaseAction

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gitlab"])

Session = Annotated[AsyncSession, Depends(get_session)]

#: GitLab's trigger vocabulary — registered by the plugin, fired here.
TRIGGERS = triggers.ConnectorTriggers(
    host="GitLab",
    change="merge request",
    opened=GitlabTrigger.MR_OPENED,
    merged=GitlabTrigger.MR_MERGED,
    closed=GitlabTrigger.MR_CLOSED,
    pushed=GitlabTrigger.PUSHED,
    release_published=GitlabTrigger.RELEASE_PUBLISHED,
)


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
    repo_name = parsing.project_path(payload)
    result: dict[str, Any] = {"linked": 0, "triggered": 0}
    if kind == GitlabEventKind.RELEASE:
        result["triggered"] = await _handle_release(session, payload, repo)
        return result
    if kind == GitlabEventKind.PUSH:
        planned = parsing.plan_push(payload)
    elif kind == GitlabEventKind.MERGE_REQUEST:
        planned = parsing.plan_merge_request(payload)
    else:
        # tag_push / pipeline / deployment: RADD-1255.
        return result

    links = await receiving.link_planned(
        session, planned, provider=VcsProvider.GITLAB, actor_id=SYSTEM_ACTOR_ID
    )
    result["linked"] = receiving.count(links)
    if kind == GitlabEventKind.PUSH:
        result["triggered"] = await receiving.fire_push(
            session, TRIGGERS.pushed, links,
            provider=VcsProvider.GITLAB, repo=repo_name,
            branch=str(payload.get("ref") or "").removeprefix("refs/heads/"),
            actor_id=SYSTEM_ACTOR_ID,
            author=triggers.host_author(payload, connection.id),
        )
    elif (action := parsing.mr_action(payload)) is not None:
        result["triggered"] = await receiving.fire_ref_action(
            session, TRIGGERS.for_action(action), links,
            provider=VcsProvider.GITLAB, repo=repo_name, action=action,
            ref_extra=parsing.mr_ref_extra(payload), actor_id=SYSTEM_ACTOR_ID,
            author=triggers.host_author(payload, connection.id),
        )

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


async def _handle_release(session: AsyncSession, payload: dict, repo) -> int:
    """A release CREATED on GitLab fires "GitLab: release published" — whether a
    version is recorded and waiting work swept is the automation's call
    (RADD-1309/1310). An update or deletion fires nothing."""
    if str(payload.get("action") or "") != ReleaseAction.CREATE:
        return 0
    tag = str(payload.get("tag") or "")
    version = triggers.version_from_tag(tag)
    if not version:
        return 0
    repo_name = parsing.project_path(payload)
    await triggers.emit_release(
        session,
        TRIGGERS.release_published,
        entity_type=GitlabEntity.REPO,
        entity_id=repo.id if repo is not None else repo_name,
        provider=VcsProvider.GITLAB,
        repo=repo_name,
        project_id=repo.project_id if repo is not None else None,
        actor_id=SYSTEM_ACTOR_ID,
        version=version,
        tag=tag,
        name=str(payload.get("name") or ""),
        notes=str(payload.get("description") or ""),
        url=str(payload.get("url") or ""),
    )
    return 1
