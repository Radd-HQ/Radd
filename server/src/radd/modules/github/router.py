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
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.vcs import policies, receiving, triggers
from radd.modules.vcs import service as vcs
from radd.modules.vcs.types import VcsProvider

from . import parsing, service, spend, timelogs
from .types import CommentAction, GithubEntity, GithubEventKind, GithubTrigger, ReleaseAction

logger = logging.getLogger(__name__)

router = APIRouter(tags=["github"])

Session = Annotated[AsyncSession, Depends(get_session)]

verify_signature = service.verify_signature

#: GitHub's trigger vocabulary (RADD-1309) — registered by the plugin, fired here.
TRIGGERS = triggers.ConnectorTriggers(
    host="GitHub",
    change="pull request",
    opened=GithubTrigger.PR_OPENED,
    merged=GithubTrigger.PR_MERGED,
    closed=GithubTrigger.PR_CLOSED,
    updated=GithubTrigger.PR_UPDATED,
    pushed=GithubTrigger.PUSHED,
    release_published=GithubTrigger.RELEASE_PUBLISHED,
    ci_completed=GithubTrigger.CI_COMPLETED,
)

#: Nothing linked, nothing fired — the answer to a delivery this receiver ignores.
_NOTHING: dict[str, int] = {"linked": 0, "triggered": 0}


@router.post("/integrations/github")
async def github_webhook(
    request: Request,
    session: Session,
    x_hub_signature_256: Annotated[str, Header()] = "",
    x_github_event: Annotated[str, Header()] = "",
    x_github_delivery: Annotated[str, Header()] = "",
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except ValueError:
        raise ForbiddenError("github webhook body is not JSON") from None

    resolved = await service.resolve_for_payload(session, payload, raw_body, x_hub_signature_256)
    if resolved is None:
        # Nothing configured, the wrong secret, or an inactive host: one answer.
        raise ForbiddenError("bad github webhook signature")
    connection, repo = resolved

    if not await receiving.claim_delivery(session, provider=VcsProvider.GITHUB, connection_id=connection.id,
            delivery_id=x_github_delivery, event_type=x_github_event, body=raw_body):
        return dict(_NOTHING)

    kind = x_github_event
    if kind in (
        GithubEventKind.ISSUE_COMMENT,
        GithubEventKind.PULL_REQUEST_REVIEW_COMMENT,
        GithubEventKind.PULL_REQUEST_REVIEW,
    ):
        return await _handle_comment(session, connection, repo, kind, payload)
    if kind == GithubEventKind.PING:
        # GitHub sends one when the hook is created; answering 200 is what makes
        # the "recent deliveries" panel show a green tick.
        return dict(_NOTHING)
    if kind == GithubEventKind.PUSH:
        planned = parsing.plan_push(payload)
        # RADD-1261: commit-author emails are the one place GitHub pairs an
        # email with a login — each match fills the identity map.
        try:
            await timelogs.record_commit_authors(session, connection, payload)
        except Exception:
            logger.exception("github: commit-author mapping failed")
    elif kind == GithubEventKind.PULL_REQUEST:
        planned = parsing.plan_pull_request(payload)
    elif kind in (GithubEventKind.CHECK_RUN, GithubEventKind.CHECK_SUITE, GithubEventKind.WORKFLOW_RUN):
        return await _handle_ci(session, kind, payload, connection, repo)
    elif kind == GithubEventKind.RELEASE:
        return await _handle_release(session, payload, repo)
    else:
        return dict(_NOTHING)

    repo_name = str((payload.get("repository") or {}).get("full_name") or "")
    links = await receiving.link_planned(
        session, planned, provider=VcsProvider.GITHUB, actor_id=SYSTEM_ACTOR_ID,
        connection_id=connection.id, repo=repo
    )
    result = {"linked": receiving.count(links), "triggered": 0}
    if kind == GithubEventKind.PUSH:
        result["triggered"] = await receiving.fire_push(
            session, TRIGGERS.pushed, links,
            provider=VcsProvider.GITHUB, repo=repo_name,
            branch=str(payload.get("ref") or "").removeprefix("refs/heads/"),
            actor_id=SYSTEM_ACTOR_ID,
            author=triggers.host_author(payload, connection.id),
        )
    elif (action := parsing.pr_action(payload)) is not None:
        result["triggered"] = await receiving.fire_ref_action(
            session, TRIGGERS.for_action(action), links,
            provider=VcsProvider.GITHUB, repo=repo_name, action=action,
            ref_extra=parsing.pr_ref_extra(payload), actor_id=SYSTEM_ACTOR_ID,
            author=triggers.host_author(payload, connection.id),
            changes=parsing.pr_changes(payload),
        )
        # RADD-1369: the repository's own "move merged issues" switch.
        if action is triggers.RefAction.MERGED and getattr(repo, "move_on_merge", False):
            result["moved"] = await policies.move_merged(session, repo, list(links), actor_id=SYSTEM_ACTOR_ID)
    logger.debug("github delivery %s: %s", x_github_delivery, result)
    return result


async def _handle_comment(
    session: AsyncSession, connection, repo, kind: str, payload: dict
) -> dict[str, Any]:
    """RADD-1261: a PR comment or review carrying `/spend` lines (or `/unspend`).
    Comments on plain issues are ignored — the convention is for pull requests."""
    result: dict[str, Any] = dict(_NOTHING)
    if repo is None or not repo.mirror_time:
        return result  # RADD-1321: mirroring is a per-repository switch, off by default
    repo_name = str((payload.get("repository") or {}).get("full_name") or "")
    action = str(payload.get("action") or "")
    if kind == GithubEventKind.ISSUE_COMMENT:
        issue = payload.get("issue") or {}
        if not issue.get("pull_request"):
            return result
        number, title, body = issue.get("number", ""), str(issue.get("title") or ""), str(issue.get("body") or "")
        comment = payload.get("comment") or {}
    else:
        pull = payload.get("pull_request") or {}
        number, title, body = pull.get("number", ""), str(pull.get("title") or ""), str(pull.get("body") or "")
        comment = payload.get("comment") or payload.get("review") or {}
        if "created_at" not in comment and comment.get("submitted_at"):
            comment = {**comment, "created_at": comment["submitted_at"]}
    if not repo_name or number == "" or not comment.get("id"):
        return result
    login = str((comment.get("user") or {}).get("login") or "")
    try:
        if action == CommentAction.DELETED:
            result["worklogs"] = await timelogs.remove_comment(
                session, connection, repo_name=repo_name, number=number, comment_id=comment["id"]
            )
        elif spend.is_unspend(str(comment.get("body") or "")) and login:
            result["worklogs"] = await timelogs.unspend(
                session, connection, repo_name=repo_name, number=number, login=login
            )
        elif action in (CommentAction.CREATED, CommentAction.EDITED, CommentAction.SUBMITTED):
            result["worklogs"] = await timelogs.reconcile_comment(
                session, connection, repo, repo_name=repo_name, number=number, title=title, body=body, comment=comment
            )
    except Exception:
        logger.exception("github: /spend mirror failed for %s #%s", repo_name, number)
        result["worklogs"] = {"error": "spend mirror failed; see the server log"}
    return result


async def _handle_ci(session: AsyncSession, kind: str, payload: dict, connection=None, repo=None) -> dict[str, int]:
    """Stamp the ref's CI badge; a FINISHED run also fires "GitHub: CI finished"
    once per linked issue (a queued or running report only moves the badge)."""
    update = parsing.plan_ci(kind, payload)
    if update is None:
        return dict(_NOTHING)
    run = payload.get(kind) or {}
    stamped = await vcs.set_ci_state(
        session, connection_id=connection.id if connection else None, repo=repo,
        provider=VcsProvider.GITHUB,
        external_ids=list(update.external_ids),
        ci_state=update.state,
        ci_url=update.url,
        run_id=run.get("id"), attempt=int(run.get("run_attempt") or 1),
        head_sha=str(run.get("head_sha") or ""),
        report_key=f"{kind}:{run.get('workflow_id') or run.get('name') or (run.get('app') or {}).get('id') or 'default'}",
        source_started_at=str(run.get("created_at") or run.get("started_at") or ""),
        source_updated_at=str(run.get("updated_at") or run.get("completed_at") or ""),
    )
    fired = 0
    if kind == GithubEventKind.WORKFLOW_RUN and update.state in tuple(triggers.CiOutcome):
        fired = await receiving.fire_ci(
            session, GithubTrigger.CI_COMPLETED, stamped,
            provider=VcsProvider.GITHUB, repo=update.repo, state=update.state, url=update.url,
            name=str(run.get("name") or "workflow"), sha=str(run.get("head_sha") or ""), run_id=run.get("id"),
            actor_id=SYSTEM_ACTOR_ID,
        )
    return {"linked": len(stamped), "triggered": fired}


async def _handle_release(session: AsyncSession, payload: dict, repo) -> dict[str, int]:
    """`release` webhook. Only `published` fires "GitHub: release published" — a
    draft, an edit or a deletion must not. The version is recorded and waiting
    work swept only when the repository's "Publish version on release" switch is
    on (RADD-1369), or by an automation on the trigger (RADD-1310)."""
    release_payload = payload.get("release") or {}
    tag = str(release_payload.get("tag_name") or "")
    version = triggers.version_from_tag(tag)
    if (
        str(payload.get("action") or "") != ReleaseAction.PUBLISHED
        or not version
        or release_payload.get("draft")
    ):
        return dict(_NOTHING)
    repo_name = str((payload.get("repository") or {}).get("full_name") or "")
    await triggers.emit_release(
        session, TRIGGERS.release_published,
        connection_id=getattr(repo, "connection_id", None),
        entity_type=GithubEntity.REPO,
        entity_id=repo.id if repo is not None else repo_name,
        provider=VcsProvider.GITHUB,
        repo=repo_name,
        project_id=getattr(repo, "project_id", None),
        actor_id=SYSTEM_ACTOR_ID,
        version=version,
        tag=tag,
        name=str(release_payload.get("name") or ""),
        notes=str(release_payload.get("body") or ""),
        url=str(release_payload.get("html_url") or ""),
    )
    # RADD-1369: the repository's own "publish version on release" switch.
    shipped = await policies.publish_release(
        session, repo, version=version, actor_id=SYSTEM_ACTOR_ID,
        name=str(release_payload.get("name") or ""), notes=str(release_payload.get("body") or ""),
    )
    return {"linked": 0, "triggered": 1, **({"shipped": shipped} if getattr(repo, "publish_on_release", False) else {})}
