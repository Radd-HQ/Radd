"""The GitLab webhook receiver. Auth: the hook's secret token, echoed verbatim as
`X-Gitlab-Token`, compared constant-time against each active connection's."""

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.vcs import policies, receiving, service as vcs, triggers
from radd.modules.vcs.types import VcsProvider

from . import parsing, service, timelogs
from .types import (
    DEPLOYMENT_OUTCOMES,
    PIPELINE_STATES,
    GitlabEntity,
    GitlabEventKind,
    GitlabTrigger,
    ReleaseAction,
)

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
    updated=GitlabTrigger.MR_UPDATED,
    pushed=GitlabTrigger.PUSHED,
    release_published=GitlabTrigger.RELEASE_PUBLISHED,
    ci_completed=GitlabTrigger.CI_COMPLETED,  # RADD-1255
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

    if not await receiving.claim_delivery(session, provider=VcsProvider.GITLAB, connection_id=connection.id,
            delivery_id=x_gitlab_event_uuid, event_type=_kind(payload, x_gitlab_event), body=raw_body):
        return {"linked": 0, "triggered": 0}

    kind = _kind(payload, x_gitlab_event)
    repo_name = parsing.project_path(payload)
    result: dict[str, Any] = {"linked": 0, "triggered": 0}
    if kind == GitlabEventKind.RELEASE:
        result["triggered"] = await _handle_release(session, payload, repo)
        return result
    if kind == GitlabEventKind.PIPELINE:
        return await _handle_pipeline(session, payload, connection, repo)
    if kind == GitlabEventKind.DEPLOYMENT:
        return await _handle_deployment(session, payload, connection, repo)
    if kind == GitlabEventKind.PUSH:
        planned = parsing.plan_push(payload)
    elif kind == GitlabEventKind.MERGE_REQUEST:
        planned = parsing.plan_merge_request(payload)
    else:
        # tag_push: nothing to link.
        return result

    links = await receiving.link_planned(
        session, planned, provider=VcsProvider.GITLAB, actor_id=SYSTEM_ACTOR_ID,
        connection_id=connection.id, repo=repo
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
            changes=parsing.mr_changes(payload),
        )
        # RADD-1369: the repository's own "move merged issues" switch.
        if action is triggers.RefAction.MERGED and getattr(repo, "move_on_merge", False):
            result["moved"] = await policies.move_merged(session, repo, list(links), actor_id=SYSTEM_ACTOR_ID)

    # RADD-1259: time added or removed on the MR → fetch the entries and mirror
    # them. Needs a token; a hook-only connection simply reports nothing.
    # RADD-1321: only a repository someone switched mirroring on for.
    if (
        kind == GitlabEventKind.MERGE_REQUEST and connection.api_token and repo is not None
        and repo.mirror_time and parsing.time_spent_changed(payload)
    ):
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


async def _handle_pipeline(session: AsyncSession, payload: dict, connection, repo=None) -> dict[str, Any]:
    """RADD-1255: stamp the ref's CI badge (branch, commit and, for an MR
    pipeline, the MR — the latest run wins), and fire "GitLab: CI finished" once
    per linked issue when the run reached an outcome. A running report only moves
    the badge; a pipeline for a ref no issue mentions writes nothing."""
    update = parsing.plan_pipeline(payload)
    if update is None:
        return {"linked": 0, "triggered": 0}
    state = PIPELINE_STATES.get(update.status, "unknown")
    stamped = await vcs.set_ci_state(
        session, connection_id=connection.id if connection else None, repo=repo, provider=VcsProvider.GITLAB, external_ids=update.external_ids, ci_state=state, ci_url=update.url,
        run_id=update.run_id, source_updated_at=update.updated_at, head_sha=update.sha,
        source_started_at=str((payload.get("object_attributes") or {}).get("created_at") or (payload.get("object_attributes") or {}).get("started_at") or ""),
    )
    fired = 0
    if state in tuple(triggers.CiOutcome):
        fired = await receiving.fire_ci(
            session, GitlabTrigger.CI_COMPLETED, stamped,
            provider=VcsProvider.GITLAB, repo=update.repo, state=state, url=update.url,
            name="pipeline", sha=update.sha, run_id=update.run_id,
            actor_id=SYSTEM_ACTOR_ID,
        )
    return {"linked": len(stamped), "triggered": fired}


async def _handle_deployment(session: AsyncSession, payload: dict, connection, repo=None) -> dict[str, Any]:
    """RADD-1255: a deployment of a linked ref reached an outcome (success,
    failed, canceled) → "GitLab: deployment finished" once per linked issue,
    with the environment. What that means — Done when production succeeds, say —
    is an automation's call. A deployment still running fires nothing."""
    update = parsing.plan_deployment(payload)
    if update is None or update.status not in DEPLOYMENT_OUTCOMES:
        return {"linked": 0, "triggered": 0}
    links = await vcs.links_for_refs(session, provider=VcsProvider.GITLAB, external_ids=update.external_ids, connection_id=connection.id, repo=repo)
    by_item: dict = {}
    for link in links:
        by_item.setdefault(link.item_id, link)
    author = triggers.host_author(payload, connection.id)
    for link in by_item.values():
        await triggers.emit_ref(
            session, GitlabTrigger.DEPLOYMENT_FINISHED, link,
            provider=VcsProvider.GITLAB, repo=update.repo, actor_id=SYSTEM_ACTOR_ID,
            payload={
                "environment": update.environment,
                "status": update.status,
                "url": update.url,
                "ref": triggers.ref_of(link),
                "sha": update.sha,
            },
            author=author,
        )
    return {"linked": len(links), "triggered": len(by_item)}


async def _handle_release(session: AsyncSession, payload: dict, repo) -> int:
    """A release CREATED on GitLab fires "GitLab: release published"; the version
    is recorded and waiting work swept when the repository's "Publish version on
    release" switch is on (RADD-1369) or an automation does it (RADD-1310). An
    update or deletion fires nothing."""
    if str(payload.get("action") or "") != ReleaseAction.CREATE:
        return 0
    tag = str(payload.get("tag") or "")
    version = triggers.version_from_tag(tag)
    if not version:
        return 0
    repo_name = parsing.project_path(payload)
    await triggers.emit_release(
        session, TRIGGERS.release_published,
        connection_id=getattr(repo, "connection_id", None),
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
    # RADD-1369: the repository's own "publish version on release" switch.
    await policies.publish_release(
        session, repo, version=version, actor_id=SYSTEM_ACTOR_ID,
        name=str(payload.get("name") or ""), notes=str(payload.get("description") or ""),
    )
    return 1
