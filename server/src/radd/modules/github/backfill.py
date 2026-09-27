"""GitHub's history walk for the backfill harness (`vcs.connector_kit.backfill`):
branches, pull requests (+ their `/spend` comments, RADD-1261) and default-branch
commits, in that order. PRs are walked in full; the commit walk is bounded."""

import logging
from typing import Any

import httpx

from radd.config import settings
from radd.modules.vcs.connector_kit import github_shape
from radd.modules.vcs.connector_kit.backfill import BackfillRun
from radd.modules.vcs.ids import branch_external_id, commit_external_id, pr_external_id
from radd.modules.vcs.types import VcsRefType

from . import timelogs

logger = logging.getLogger(__name__)

#: The per-PR comment counter a GitHub report adds.
COMMENTS = "comments"


async def walk(run: BackfillRun) -> None:
    name, web_base, repo = run.name, run.web_base, run.repo
    run.report.extra[COMMENTS] = 0
    async for branch in run.client.paged(f"/repos/{name}/branches"):
        run.report.branches += 1
        branch_name = str(branch.get("name") or "")
        await run.link(
            texts=[branch_name],
            ref_type=VcsRefType.BRANCH,
            external_id=branch_external_id(name, branch_name),
            title=branch_name,
            url=f"{web_base}/tree/{branch_name}",
        )

    async for pull in run.client.paged(f"/repos/{name}/pulls", {"state": "all", "sort": "updated", "direction": "desc"}):
        run.report.pull_requests += 1
        number = pull.get("number")
        head_ref = ((pull.get("head") or {}).get("ref")) or ""
        title = pull.get("title") or ""
        await run.link(
            texts=[title, pull.get("body"), head_ref],
            ref_type=VcsRefType.PULL_REQUEST,
            external_id=pr_external_id(name, number),
            title=github_shape.pr_title(pull),
            url=str(pull.get("html_url") or f"{web_base}/pull/{number}"),
            status=github_shape.pr_status(pull).value,
        )
        # RADD-1261: the PR's comments (issue + review), replayed through the
        # /spend convention as one whole-scope reconcile — only when it has
        # comments at all, so a quiet PR costs nothing. RADD-1321: and only for a
        # repository that mirrors time.
        if repo.mirror_time and (
            int(pull.get("comments") or 0) + int(pull.get("review_comments") or 0) > 0 or "comments" not in pull
        ):
            comments = await _comments(run, number)
            run.report.extra[COMMENTS] += len(comments)
            if comments:
                await run.mirror(f"#{number}", timelogs.reconcile_pull_request(
                    run.session, run.connection, repo,
                    repo_name=name, number=number, title=title, body=str(pull.get("body") or ""),
                    head_branch=head_ref, comments=comments,
                ))

    async for commit in run.client.paged(f"/repos/{name}/commits", {"sha": repo.default_branch}, cap=run.max_commits):
        run.report.commits += 1
        sha = str(commit.get("sha") or "")
        message = ((commit.get("commit") or {}).get("message")) or ""
        await run.link(
            texts=[message],
            ref_type=VcsRefType.COMMIT,
            external_id=commit_external_id(name, sha),
            title=message.splitlines()[0][:300] if message else sha[:12],
            url=str(commit.get("html_url") or f"{web_base}/commit/{sha}"),
        )


async def _comments(run: BackfillRun, number: Any) -> list[dict[str, Any]]:
    """A PR's issue and review comments. Locked or disabled comments cost only
    their time: the links still count."""
    cap = settings.github_backfill_max_comments
    comments: list[dict[str, Any]] = []
    try:
        async for comment in run.client.paged(f"/repos/{run.name}/issues/{number}/comments", cap=cap):
            comments.append(comment)
        async for comment in run.client.paged(f"/repos/{run.name}/pulls/{number}/comments", cap=cap):
            comments.append(comment)
    except httpx.HTTPStatusError as exc:
        run.report.errors.append(f"Comments for #{number} could not be read (HTTP {exc.response.status_code}).")
        logger.info("github backfill %s: comments of #%s unreadable (%s)", run.name, number, exc.response.status_code)
    return comments
