"""Pure GitHub webhook → planned vcs-link parsing. No I/O; external ids come from
`vcs.ids`. Pull requests and releases are parsed by `vcs.connector_kit.github_shape`,
which Forgejo shares."""

from dataclasses import dataclass

from radd.modules.vcs.ids import branch_external_id, commit_external_id
from radd.modules.vcs.keys import PlannedLink, extract_keys
from radd.modules.vcs.types import VcsRefType


def plan_push(payload: dict) -> list[PlannedLink]:
    """Branch + commit links from a GitHub push event. Tag pushes (`refs/tags/`)
    plan nothing: a release event carries the version, and a tag name is not a
    branch."""
    repository = payload.get("repository") or {}
    repo_name = repository.get("full_name", "")
    html_url = repository.get("html_url", "")
    ref = payload.get("ref") or ""
    if not ref.startswith("refs/heads/"):
        return []
    branch = ref.removeprefix("refs/heads/")
    planned: list[PlannedLink] = []

    for key in extract_keys(branch):
        planned.append(
            PlannedLink(
                item_key=key,
                ref_type=VcsRefType.BRANCH,
                external_id=branch_external_id(repo_name, branch),
                title=branch,
                url=f"{html_url}/tree/{branch}" if html_url else "",
            )
        )

    for commit in payload.get("commits") or []:
        message = commit.get("message") or ""
        sha = str(commit.get("id", ""))
        for key in extract_keys(message):
            planned.append(
                PlannedLink(
                    item_key=key,
                    ref_type=VcsRefType.COMMIT,
                    external_id=commit_external_id(repo_name, sha),
                    title=message.splitlines()[0][:300] if message else "commit",
                    url=commit.get("url") or (f"{html_url}/commit/{sha}" if html_url else ""),
                )
            )
    return planned


@dataclass(frozen=True)
class CiUpdate:
    repo: str
    external_ids: tuple[str, ...]
    state: str
    url: str


_CI_STATES = {
    "success": "success",
    "neutral": "success",
    "skipped": "success",
    "failure": "failure",
    "timed_out": "failure",
    "action_required": "failure",
    "startup_failure": "failure",
    "cancelled": "cancelled",
    "stale": "cancelled",
    "in_progress": "running",
    "queued": "running",
    "waiting": "running",
    "pending": "running",
    "requested": "running",
}


def plan_ci(kind: str, payload: dict) -> CiUpdate | None:
    """CI state for a ref from a check_run, check_suite or workflow_run event.
    Returns None when the payload names no ref this connector can stamp."""
    run = payload.get(kind) or {}
    repository = (payload.get("repository") or {}).get("full_name") or ""
    branch = str(run.get("head_branch") or (run.get("check_suite") or {}).get("head_branch") or "")
    sha = str(run.get("head_sha") or "")
    status = str(run.get("conclusion") or run.get("status") or "")
    if not repository or not (branch or sha):
        return None
    external_ids: list[str] = []
    if branch:
        external_ids.append(branch_external_id(repository, branch))
    if sha:
        external_ids.append(commit_external_id(repository, sha))
    url = str(run.get("html_url") or run.get("details_url") or "")
    return CiUpdate(repository, tuple(external_ids), _CI_STATES.get(status, "unknown"), url)
