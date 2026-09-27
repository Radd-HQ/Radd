"""The Forgejo/Gitea webhook receiver: authentication, linking and triggers are the
connector kit's (`vcs.receiving`); this reads Forgejo's headers and events."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.vcs import receiving, triggers
from radd.modules.vcs import service as vcs
from radd.modules.vcs.connector_kit import github_shape
from radd.modules.vcs.ids import branch_external_id, commit_external_id
from radd.modules.vcs.types import VcsProvider

from . import parsing, service, timelogs
from .types import CiState, ForgejoEventKind, ForgejoTrigger

logger = logging.getLogger(__name__)

router = APIRouter(tags=["forgejo"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/integrations/forgejo")
async def forgejo_webhook(
    request: Request,
    session: Session,
    x_forgejo_signature: Annotated[str, Header()] = "",
    x_gitea_signature: Annotated[str, Header()] = "",
    x_forgejo_event: Annotated[str, Header()] = "",
    x_gitea_event: Annotated[str, Header()] = "",
) -> dict[str, Any]:
    """Forgejo/Gitea receiver: HMAC-SHA256 of the RAW body against the signing connection's secret."""
    kind = x_forgejo_event or x_gitea_event
    # Gitea also sends GitHub's delivery header, for GitHub compatibility.
    delivery_id = (request.headers.get("x-forgejo-delivery") or request.headers.get("x-gitea-delivery")
                   or request.headers.get("x-github-delivery", ""))
    delivery = await receiving.accept(
        session, service.store, raw_body=await request.body(),
        credential=x_forgejo_signature or x_gitea_signature, delivery_id=delivery_id, kind_of=lambda _payload: kind,
    )
    if delivery is None:
        return receiving.nothing()
    payload, connection, repo = delivery.payload, delivery.connection, delivery.repo

    if kind == ForgejoEventKind.PUSH:
        return await receiving.deliver_push(session, delivery, parsing.plan_push(payload))
    if kind in (ForgejoEventKind.WORKFLOW_RUN, ForgejoEventKind.WORKFLOW_JOB):
        # Spec 111: CI state for a ref. Forgejo Actions is not on every host, so
        # a payload we cannot read is a no-op rather than an error.
        return await _handle_workflow_run(session, payload, connection, repo)
    if kind == ForgejoEventKind.RELEASE:
        return await _handle_release(session, payload, repo)
    if kind != ForgejoEventKind.PULL_REQUEST:
        return receiving.nothing()

    result = await receiving.deliver_change(
        session, delivery, github_shape.plan_pull_request(payload),
        action=github_shape.pr_action(payload), ref_extra=github_shape.pr_ref_extra(payload),
        changes=github_shape.pr_changes(payload),
    )
    # RADD-1260: Forgejo has no tracked-time webhook, so EVERY pull_request
    # delivery reconciles that PR's time. Needs a token; best-effort — the link
    # half has already landed. RADD-1321: only a repository that mirrors time.
    if connection.api_token and repo is not None and repo.mirror_time:
        pull = payload.get("pull_request") or {}
        try:
            report = await timelogs.reconcile_pull_request(
                session,
                connection,
                repo,
                full_name=delivery.repo_name,
                index=pull.get("number", ""),
                title=str(pull.get("title") or ""),
                head_branch=str((pull.get("head") or {}).get("ref") or ""),
                body=str(pull.get("body") or ""),
            )
            result["worklogs"] = report.as_dict()
        except Exception:
            logger.exception("forgejo: tracked-time mirror failed for %s #%s", delivery.repo_name, pull.get("number"))
            result["worklogs"] = {"error": "tracked-time fetch failed; see the server log"}
    return result


_CI_STATES = {
    "success": CiState.SUCCESS,
    "failure": CiState.FAILURE,
    "cancelled": CiState.CANCELLED,
    "in_progress": CiState.RUNNING,
    "queued": CiState.RUNNING,
    "waiting": CiState.RUNNING,
}


async def _handle_workflow_run(session: AsyncSession, payload: dict, connection=None, repo=None) -> dict[str, int]:
    """Stamp the ref's CI badge; a FINISHED run also fires "Forgejo: CI finished"
    once per linked issue (a queued or running report only moves the badge)."""
    run = payload.get("workflow_run") or payload.get("workflow_job") or {}
    repository = github_shape.repo_full_name(payload)
    branch = str(run.get("head_branch") or "")
    sha = str(run.get("head_sha") or "")
    status = str(run.get("conclusion") or run.get("status") or "")
    if not repository or not (branch or sha):
        return receiving.nothing()
    ci_state = _CI_STATES.get(status, CiState.UNKNOWN)
    external_ids = []
    if branch:
        external_ids.append(branch_external_id(repository, branch))
    if sha:
        external_ids.append(commit_external_id(repository, sha))
    url = str(run.get("html_url") or "")
    stamped = await vcs.set_ci_state(
        session, connection_id=connection.id if connection else None, repo=repo,
        provider=VcsProvider.FORGEJO,
        external_ids=external_ids,
        ci_state=str(ci_state),
        ci_url=url,
        run_id=run.get("id"), attempt=int(run.get("run_attempt") or 1),
        head_sha=sha, report_key=f"{'workflow' if payload.get('workflow_run') else 'job'}:{run.get('workflow_id') or run.get('name') or 'default'}",
        source_started_at=str(run.get("created_at") or run.get("started_at") or ""),
        source_updated_at=str(run.get("updated_at") or run.get("completed_at") or ""),
    )
    fired = 0
    if payload.get("workflow_run") and ci_state in tuple(triggers.CiOutcome):
        fired = await receiving.fire_ci(
            session, ForgejoTrigger.CI_COMPLETED, stamped,
            provider=VcsProvider.FORGEJO, repo=repository, state=str(ci_state), url=url,
            name=str(run.get("name") or "workflow"), sha=sha, run_id=run.get("id"),
            actor_id=SYSTEM_ACTOR_ID,
        )
    return {"linked": len(stamped), "triggered": fired}


async def _handle_release(session: AsyncSession, payload: dict, repo) -> dict[str, int]:
    """Only a published, non-draft release fires "Forgejo: release published"."""
    release = github_shape.published_release(payload)
    if release is None:
        return receiving.nothing()
    return await receiving.release_published(
        session, service.CONNECTOR, repo, repo_name=github_shape.repo_full_name(payload),
        tag=release.tag, name=release.name, notes=release.notes, url=release.url,
    )
