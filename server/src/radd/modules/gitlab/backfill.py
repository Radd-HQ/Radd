"""GitLab's history walk for the backfill harness (`vcs.connector_kit.backfill`):
branches, merge requests (+ their time, RADD-1259) and default-branch commits, in
that order. Only merge requests reporting `time_stats.total_time_spent > 0` are
fetched for time — one GraphQL round trip each, none for the rest."""

from urllib.parse import quote

from radd.modules.vcs.connector_kit.backfill import BackfillRun
from radd.modules.vcs.ids import branch_external_id, commit_external_id, pr_external_id
from radd.modules.vcs.types import VcsRefType

from . import timelogs
from .parsing import mr_status, mr_title

#: GitLab's own names for its report counters, beside the shared `pull_requests`.
MERGE_REQUESTS = "merge_requests"
TIMED_MERGE_REQUESTS = "timed_merge_requests"


def project_api_path(full_name: str) -> str:
    """`group/sub/project` → `/projects/group%2Fsub%2Fproject`."""
    return f"/projects/{quote(full_name.strip('/'), safe='')}"


async def walk(run: BackfillRun) -> None:
    name, web_base, repo = run.name, run.web_base, run.repo
    api = project_api_path(name)
    extra = run.report.extra
    extra[MERGE_REQUESTS] = extra[TIMED_MERGE_REQUESTS] = 0

    async for branch in run.client.paged(f"{api}/repository/branches"):
        run.report.branches += 1
        branch_name = str(branch.get("name") or "")
        await run.link(
            texts=[branch_name],
            ref_type=VcsRefType.BRANCH,
            external_id=branch_external_id(name, branch_name),
            title=branch_name,
            url=str(branch.get("web_url") or f"{web_base}/-/tree/{branch_name}"),
        )

    async for mr in run.client.paged(f"{api}/merge_requests", {"state": "all", "order_by": "updated_at", "sort": "desc"}):
        run.report.pull_requests += 1
        extra[MERGE_REQUESTS] += 1
        iid = mr.get("iid")
        title = str(mr.get("title") or "")
        source_branch = str(mr.get("source_branch") or "")
        description = str(mr.get("description") or "")
        await run.link(
            texts=[source_branch, title, description],
            ref_type=VcsRefType.MERGE_REQUEST,
            external_id=pr_external_id(name, iid),
            title=mr_title({"iid": iid, "title": title}),
            url=str(mr.get("web_url") or f"{web_base}/-/merge_requests/{iid}"),
            status=mr_status(mr).value,
        )
        # RADD-1321: only a repository that mirrors time.
        if repo.mirror_time and int((mr.get("time_stats") or {}).get("total_time_spent") or 0) > 0:
            mirrored = await run.mirror(f"!{iid}", timelogs.reconcile_merge_request(
                run.session, run.connection, repo,
                project_path=name, iid=iid, title=title, source_branch=source_branch,
                description=description, transport=run.transport,
            ))
            extra[TIMED_MERGE_REQUESTS] += int(mirrored)

    async for commit in run.client.paged(f"{api}/repository/commits", {"ref_name": repo.default_branch}, cap=run.max_commits):
        run.report.commits += 1
        sha = str(commit.get("id") or "")
        message = str(commit.get("message") or "")
        await run.link(
            texts=[message],
            ref_type=VcsRefType.COMMIT,
            external_id=commit_external_id(name, sha),
            title=message.splitlines()[0][:300] if message else sha[:12],
            url=str(commit.get("web_url") or f"{web_base}/-/commit/{sha}"),
        )
