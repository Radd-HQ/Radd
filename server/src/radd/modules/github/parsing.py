"""Pure GitHub webhook → planned vcs-link parsing. No I/O; external ids come from
`vcs.ids`."""

from dataclasses import dataclass

from radd.modules.vcs.ids import branch_external_id, commit_external_id, pr_external_id
from radd.modules.vcs.keys import PlannedLink, extract_keys
from radd.modules.vcs.triggers import COMMITS_CHANGE, RefAction, diff_entries
from radd.modules.vcs.types import RefStatus, VcsRefType

from .types import PrAction


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


def pr_status(pull_request: dict) -> RefStatus:
    if pull_request.get("merged") or pull_request.get("merged_at"):
        return RefStatus.MERGED
    if pull_request.get("state") == RefStatus.CLOSED.value:
        return RefStatus.CLOSED
    return RefStatus.OPEN


def plan_pull_request(payload: dict) -> list[PlannedLink]:
    """Links from a GitHub pull_request event. Keys come from the head branch,
    title, and body; re-deliveries update in place via the stable external id
    `pr:<repo>:<number>`."""
    pull_request = payload.get("pull_request") or {}
    repository = payload.get("repository") or {}
    repo_name = repository.get("full_name", "")
    number = pull_request.get("number", "")
    title = pull_request.get("title") or ""
    head_branch = (pull_request.get("head") or {}).get("ref")
    status = pr_status(pull_request)
    return [
        PlannedLink(
            item_key=key,
            ref_type=VcsRefType.PULL_REQUEST,
            external_id=pr_external_id(repo_name, number),
            title=f"{title[:280]} (#{number})".strip() if title else f"#{number}",
            url=pull_request.get("html_url", ""),
            status=status.value,
        )
        for key in (extract_keys(head_branch, title, pull_request.get("body")) or [""])
    ]


def pr_action(payload: dict) -> RefAction | None:
    """What this delivery DID to the pull request (RADD-1309) — by its `action`,
    never its state, which every later edit of a merged PR repeats."""
    action = str(payload.get("action") or "")
    if action in (PrAction.OPENED, PrAction.REOPENED):
        return RefAction.OPENED
    if action == PrAction.CLOSED:
        merged = pr_status(payload.get("pull_request") or {}) is RefStatus.MERGED
        return RefAction.MERGED if merged else RefAction.CLOSED
    if action in (PrAction.EDITED, PrAction.SYNCHRONIZE):
        return RefAction.UPDATED
    return None


def pr_changes(payload: dict) -> list[dict]:
    """What an update changed (RADD-1330), as the kernel diff: an `edited`
    delivery's `changes` gives `{from}` per field (the new value is on the pull
    request); a synchronize is new commits, `before` → `after` when sent."""
    pull = payload.get("pull_request") or {}
    if str(payload.get("action") or "") == PrAction.SYNCHRONIZE:
        return diff_entries([(COMMITS_CHANGE, payload.get("before") or "old", payload.get("after") or "new")])
    return diff_entries(
        (name, (value or {}).get("from"), pull.get(name))
        for name, value in (payload.get("changes") or {}).items()
        if isinstance(value, dict)
    )


def pr_ref_extra(payload: dict) -> dict[str, object]:
    """The `ref` fields a trigger carries that the link row does not store."""
    pull_request = payload.get("pull_request") or {}
    return {
        "number": pull_request.get("number"),
        "source_branch": (pull_request.get("head") or {}).get("ref"),
        "target_branch": (pull_request.get("base") or {}).get("ref"),
    }


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
