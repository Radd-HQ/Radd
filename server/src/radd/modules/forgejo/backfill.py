"""Forgejo's history walk for the backfill harness (`vcs.connector_kit.backfill`):
branches, pull requests (+ their tracked time, RADD-1260) and default-branch
commits, in that order. PRs are walked in full — a merged PR is the most
information-dense link there is; the commit walk is bounded."""

from radd.modules.vcs.connector_kit import github_shape
from radd.modules.vcs.connector_kit.backfill import BackfillRun
from radd.modules.vcs.ids import branch_external_id, commit_external_id, pr_external_id
from radd.modules.vcs.types import VcsRefType

from . import timelogs


async def walk(run: BackfillRun) -> None:
    name, web_base, repo = run.name, run.web_base, run.repo
    async for branch in run.client.paged(f"/repos/{name}/branches"):
        run.report.branches += 1
        branch_name = str(branch.get("name") or "")
        await run.link(
            texts=[branch_name],
            ref_type=VcsRefType.BRANCH,
            external_id=branch_external_id(name, branch_name),
            title=branch_name,
            url=f"{web_base}/src/branch/{branch_name}",
        )

    async for pull in run.client.paged(f"/repos/{name}/pulls", {"state": "all", "sort": "recentupdate"}):
        run.report.pull_requests += 1
        number = pull.get("number")
        head_ref = ((pull.get("head") or {}).get("ref")) or ""
        await run.link(
            texts=[pull.get("title"), pull.get("body"), head_ref],
            ref_type=VcsRefType.PULL_REQUEST,
            external_id=pr_external_id(name, number),
            title=github_shape.pr_title(pull),
            url=str(pull.get("html_url") or f"{web_base}/pulls/{number}"),
            status=github_shape.pr_status(pull).value,
        )
        # RADD-1260: the PR's tracked time — one paged GET each; a repeat run is a
        # no-op. RADD-1321: only when the repository mirrors time.
        if repo.mirror_time:
            await run.mirror(f"#{number}", timelogs.reconcile_pull_request(
                run.session, run.connection, repo,
                full_name=name, index=number, title=str(pull.get("title") or ""),
                head_branch=head_ref, body=str(pull.get("body") or ""), transport=run.transport,
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
