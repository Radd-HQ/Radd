import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.vcs import receiving, triggers
from radd.modules.vcs import service as vcs
from radd.modules.vcs.ids import branch_external_id, commit_external_id
from radd.modules.vcs.types import VcsProvider

from . import parsing, service, timelogs
from .types import CiState, ForgejoEntity, ForgejoEventKind, ForgejoTrigger, ReleaseAction

logger = logging.getLogger(__name__)

router = APIRouter(tags=["forgejo"])

Session = Annotated[AsyncSession, Depends(get_session)]


# Signature verification moved to service.verify_signature in spec 111 — the
# receiver no longer knows which secret to use until it has resolved the
# connection, so the check belongs next to that lookup. Re-exported because
# tests/test_connectors.py imports it from here.
verify_signature = service.verify_signature

#: Forgejo's trigger vocabulary (RADD-1309) — registered by the plugin, fired here.
TRIGGERS = triggers.ConnectorTriggers(
    host="Forgejo",
    change="pull request",
    opened=ForgejoTrigger.PR_OPENED,
    merged=ForgejoTrigger.PR_MERGED,
    closed=ForgejoTrigger.PR_CLOSED,
    pushed=ForgejoTrigger.PUSHED,
    release_published=ForgejoTrigger.RELEASE_PUBLISHED,
    ci_completed=ForgejoTrigger.CI_COMPLETED,
)

#: Nothing linked, nothing fired — the answer to a delivery this receiver ignores.
_NOTHING: dict[str, int] = {"linked": 0, "triggered": 0}


@router.post("/integrations/forgejo")
async def forgejo_webhook(
    request: Request,
    session: Session,
    x_forgejo_signature: Annotated[str, Header()] = "",
    x_gitea_signature: Annotated[str, Header()] = "",
    x_forgejo_event: Annotated[str, Header()] = "",
    x_gitea_event: Annotated[str, Header()] = "",
) -> dict[str, Any]:
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
    connection, _repo = resolved

    kind = x_forgejo_event or x_gitea_event
    if kind == ForgejoEventKind.PUSH:
        planned = parsing.plan_push(payload)
    elif kind == ForgejoEventKind.PULL_REQUEST:
        planned = parsing.plan_pull_request(payload)
    elif kind in (ForgejoEventKind.WORKFLOW_RUN, ForgejoEventKind.WORKFLOW_JOB):
        # Spec 111: CI state for a ref. Forgejo Actions is not on every host, so
        # a payload we cannot read is a no-op rather than an error.
        return await _handle_workflow_run(session, payload)
    elif kind == ForgejoEventKind.RELEASE:
        return await _handle_release(session, payload, _repo)
    else:
        return dict(_NOTHING)

    repo_name = str((payload.get("repository") or {}).get("full_name") or "")
    links = await receiving.link_planned(
        session, planned, provider=VcsProvider.FORGEJO, actor_id=SYSTEM_ACTOR_ID
    )
    result: dict[str, Any] = {"linked": receiving.count(links), "triggered": 0}
    if kind == ForgejoEventKind.PUSH:
        result["triggered"] = await receiving.fire_push(
            session, TRIGGERS.pushed, links,
            provider=VcsProvider.FORGEJO, repo=repo_name,
            branch=str(payload.get("ref") or "").removeprefix("refs/heads/"),
            actor_id=SYSTEM_ACTOR_ID,
            author=triggers.host_author(payload, connection.id),
        )
    elif (action := parsing.pr_action(payload)) is not None:
        result["triggered"] = await receiving.fire_ref_action(
            session, TRIGGERS.for_action(action), links,
            provider=VcsProvider.FORGEJO, repo=repo_name, action=action,
            ref_extra=parsing.pr_ref_extra(payload), actor_id=SYSTEM_ACTOR_ID,
            author=triggers.host_author(payload, connection.id),
        )

    # RADD-1260: Forgejo has no tracked-time webhook, so EVERY pull_request
    # delivery reconciles that PR's time. Needs a token; best-effort — the link
    # half has already landed.
    # RADD-1321: only a repository someone switched mirroring on for.
    if kind == ForgejoEventKind.PULL_REQUEST and connection.api_token and _repo is not None and _repo.mirror_time:
        pull = payload.get("pull_request") or {}
        full_name = str((payload.get("repository") or {}).get("full_name") or "")
        try:
            report = await timelogs.reconcile_pull_request(
                session,
                connection,
                _repo,
                full_name=full_name,
                index=pull.get("number", ""),
                title=str(pull.get("title") or ""),
                head_branch=str((pull.get("head") or {}).get("ref") or ""),
                body=str(pull.get("body") or ""),
            )
            result["worklogs"] = report.as_dict()
        except Exception:
            logger.exception("forgejo: tracked-time mirror failed for %s #%s", full_name, pull.get("number"))
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


async def _handle_workflow_run(session: AsyncSession, payload: dict) -> dict[str, int]:
    """Stamp the ref's CI badge; a FINISHED run also fires "Forgejo: CI finished"
    once per linked issue (a queued or running report only moves the badge)."""
    run = payload.get("workflow_run") or payload.get("workflow_job") or {}
    repository = (payload.get("repository") or {}).get("full_name") or ""
    branch = str(run.get("head_branch") or "")
    sha = str(run.get("head_sha") or "")
    status = str(run.get("conclusion") or run.get("status") or "")
    if not repository or not (branch or sha):
        return dict(_NOTHING)
    ci_state = _CI_STATES.get(status, CiState.UNKNOWN)
    external_ids = []
    if branch:
        external_ids.append(branch_external_id(repository, branch))
    if sha:
        external_ids.append(commit_external_id(repository, sha))
    url = str(run.get("html_url") or "")
    stamped = await vcs.set_ci_state(
        session,
        provider=VcsProvider.FORGEJO,
        external_ids=external_ids,
        ci_state=str(ci_state),
        ci_url=url,
    )
    fired = 0
    if ci_state in tuple(triggers.CiOutcome):
        fired = await receiving.fire_ci(
            session, ForgejoTrigger.CI_COMPLETED, stamped,
            provider=VcsProvider.FORGEJO, repo=repository, state=str(ci_state), url=url,
            actor_id=SYSTEM_ACTOR_ID,
        )
    return {"linked": len(stamped), "triggered": fired}


async def _handle_release(session: AsyncSession, payload: dict, repo) -> dict[str, int]:
    """`release` webhook. Only `published` fires "Forgejo: release published" — a
    draft or a deletion must not. Whether a version is recorded and waiting work
    swept is the automation's call (RADD-1309/1310); the receiver used to do it
    unasked for any repository with a default project."""
    release_payload = payload.get("release") or {}
    tag = str(release_payload.get("tag_name") or "")
    version = triggers.version_from_tag(tag)
    if str(payload.get("action") or "") != ReleaseAction.PUBLISHED or not version:
        return dict(_NOTHING)
    repo_name = str((payload.get("repository") or {}).get("full_name") or "")
    await triggers.emit_release(
        session,
        TRIGGERS.release_published,
        entity_type=ForgejoEntity.REPO,
        entity_id=repo.id if repo is not None else repo_name,
        provider=VcsProvider.FORGEJO,
        repo=repo_name,
        project_id=getattr(repo, "project_id", None),
        actor_id=SYSTEM_ACTOR_ID,
        version=version,
        tag=tag,
        name=str(release_payload.get("name") or ""),
        notes=str(release_payload.get("body") or ""),
        url=str(release_payload.get("html_url") or ""),
    )
    return {"linked": 0, "triggered": 1}
