"""The GitHub webhook receiver: authentication, linking and triggers are the
connector kit's (`vcs.receiving`); this reads GitHub's headers and events."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.vcs import receiving, triggers
from radd.modules.vcs import service as vcs
from radd.modules.vcs.connector_kit import github_shape
from radd.modules.vcs.types import VcsProvider

from . import parsing, service, spend, timelogs
from .types import CommentAction, GithubEventKind, GithubTrigger

logger = logging.getLogger(__name__)

router = APIRouter(tags=["github"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/integrations/github")
async def github_webhook(
    request: Request,
    session: Session,
    x_hub_signature_256: Annotated[str, Header()] = "",
    x_github_event: Annotated[str, Header()] = "",
    x_github_delivery: Annotated[str, Header()] = "",
) -> dict[str, Any]:
    kind = x_github_event
    delivery = await receiving.accept(
        session, service.store, raw_body=await request.body(), credential=x_hub_signature_256,
        delivery_id=x_github_delivery, kind_of=lambda _payload: kind,
    )
    if delivery is None:
        return receiving.nothing()
    payload, connection, repo = delivery.payload, delivery.connection, delivery.repo

    if kind in (
        GithubEventKind.ISSUE_COMMENT,
        GithubEventKind.PULL_REQUEST_REVIEW_COMMENT,
        GithubEventKind.PULL_REQUEST_REVIEW,
    ):
        return await _handle_comment(session, connection, repo, kind, payload)
    if kind == GithubEventKind.PUSH:
        # RADD-1261: commit-author emails are the one place GitHub pairs an
        # email with a login — each match fills the identity map.
        try:
            await timelogs.record_commit_authors(session, connection, payload)
        except Exception:
            logger.exception("github: commit-author mapping failed")
        return await receiving.deliver_push(session, delivery, parsing.plan_push(payload))
    if kind == GithubEventKind.PULL_REQUEST:
        return await receiving.deliver_change(
            session, delivery, github_shape.plan_pull_request(payload),
            action=github_shape.pr_action(payload), ref_extra=github_shape.pr_ref_extra(payload),
            changes=github_shape.pr_changes(payload),
        )
    if kind in (GithubEventKind.CHECK_RUN, GithubEventKind.CHECK_SUITE, GithubEventKind.WORKFLOW_RUN):
        return await _handle_ci(session, kind, payload, connection, repo)
    if kind == GithubEventKind.RELEASE:
        return await _handle_release(session, payload, repo)
    # `ping` (sent when the hook is created — a 200 is the green tick) and every
    # event this connector does not read.
    return receiving.nothing()


async def _handle_comment(
    session: AsyncSession, connection, repo, kind: str, payload: dict
) -> dict[str, Any]:
    """RADD-1261: a PR comment or review carrying `/spend` lines (or `/unspend`).
    Comments on plain issues are ignored — the convention is for pull requests."""
    result: dict[str, Any] = receiving.nothing()
    if repo is None or not repo.mirror_time:
        return result  # RADD-1321: mirroring is a per-repository switch, off by default
    repo_name = github_shape.repo_full_name(payload)
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
        return receiving.nothing()
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
    """Only a published, non-draft release fires "GitHub: release published"."""
    release = github_shape.published_release(payload)
    if release is None:
        return receiving.nothing()
    return await receiving.release_published(
        session, service.CONNECTOR, repo, repo_name=github_shape.repo_full_name(payload),
        tag=release.tag, name=release.name, notes=release.notes, url=release.url,
    )
