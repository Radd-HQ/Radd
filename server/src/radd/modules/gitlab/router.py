"""The GitLab webhook receiver: authentication, linking and triggers are the
connector kit's (`vcs.receiving`); this reads GitLab's events — and its pipelines,
deployments and time, which only GitLab reports this way."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.vcs import receiving, service as vcs, triggers
from radd.modules.vcs.types import VcsProvider

from . import parsing, service, timelogs
from .types import (
    DEPLOYMENT_OUTCOMES,
    PIPELINE_STATES,
    GitlabEventKind,
    GitlabTrigger,
    ReleaseAction,
)

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
    delivery = await receiving.accept(
        session, service.store, raw_body=await request.body(), credential=x_gitlab_token,
        delivery_id=x_gitlab_event_uuid, kind_of=lambda payload: _kind(payload, x_gitlab_event),
    )
    if delivery is None:
        return receiving.nothing()
    payload, connection, repo, kind = delivery.payload, delivery.connection, delivery.repo, delivery.kind

    if kind == GitlabEventKind.RELEASE:
        return await _handle_release(session, payload, repo)
    if kind == GitlabEventKind.PIPELINE:
        return await _handle_pipeline(session, payload, connection, repo)
    if kind == GitlabEventKind.DEPLOYMENT:
        return await _handle_deployment(session, payload, connection, repo)
    if kind == GitlabEventKind.PUSH:
        return await receiving.deliver_push(session, delivery, parsing.plan_push(payload))
    if kind != GitlabEventKind.MERGE_REQUEST:
        return receiving.nothing()  # tag_push and the rest: nothing to link

    result = await receiving.deliver_change(
        session, delivery, parsing.plan_merge_request(payload),
        action=parsing.mr_action(payload), ref_extra=parsing.mr_ref_extra(payload),
        changes=parsing.mr_changes(payload),
    )
    # RADD-1259: time added or removed on the MR → fetch the entries and mirror
    # them. Needs a token; a hook-only connection simply reports nothing.
    # RADD-1321: only a repository that mirrors time.
    if connection.api_token and repo is not None and repo.mirror_time and parsing.time_spent_changed(payload):
        attributes = payload.get("object_attributes") or {}
        try:
            report = await timelogs.reconcile_merge_request(
                session,
                connection,
                repo,
                project_path=delivery.repo_name,
                iid=attributes.get("iid", ""),
                title=str(attributes.get("title") or ""),
                source_branch=str(attributes.get("source_branch") or ""),
                description=str(attributes.get("description") or ""),
            )
            result["worklogs"] = report.as_dict()
        except Exception:  # the link half already landed; time is best-effort
            logger.exception("gitlab: timelog mirror failed for %s !%s", delivery.repo_name, attributes.get("iid"))
            result["worklogs"] = {"error": "timelog fetch failed; see the server log"}
    return result


async def _handle_pipeline(session: AsyncSession, payload: dict, connection, repo=None) -> dict[str, Any]:
    """RADD-1255: stamp the ref's CI badge (branch, commit and, for an MR
    pipeline, the MR — the latest run wins), and fire "GitLab: CI finished" once
    per linked issue when the run reached an outcome. A running report only moves
    the badge; a pipeline for a ref no issue mentions writes nothing."""
    update = parsing.plan_pipeline(payload)
    if update is None:
        return receiving.nothing()
    state = PIPELINE_STATES.get(update.status, "unknown")
    attributes = payload.get("object_attributes") or {}
    stamped = await vcs.set_ci_state(
        session, connection_id=connection.id if connection else None, repo=repo, provider=VcsProvider.GITLAB,
        external_ids=update.external_ids, ci_state=state, ci_url=update.url,
        run_id=update.run_id, source_updated_at=update.updated_at, head_sha=update.sha,
        source_started_at=str(attributes.get("created_at") or attributes.get("started_at") or ""),
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
        return receiving.nothing()
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


async def _handle_release(session: AsyncSession, payload: dict, repo) -> dict[str, Any]:
    """A release CREATED on GitLab is its publication; an update or deletion
    fires nothing."""
    if str(payload.get("action") or "") != ReleaseAction.CREATE:
        return receiving.nothing()
    return await receiving.release_published(
        session, service.CONNECTOR, repo, repo_name=parsing.project_path(payload),
        tag=str(payload.get("tag") or ""), name=str(payload.get("name") or ""),
        notes=str(payload.get("description") or ""), url=str(payload.get("url") or ""),
    )
