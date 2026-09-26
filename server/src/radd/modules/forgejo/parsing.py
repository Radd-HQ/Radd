"""Pure Forgejo/Gitea webhook → planned vcs-link parsing. No I/O; external ids come
from `vcs.ids`."""

from radd.modules.vcs.ids import branch_external_id, commit_external_id, pr_external_id
from radd.modules.vcs.keys import PlannedLink, extract_keys
from radd.modules.vcs.triggers import COMMITS_CHANGE, RefAction, diff_entries
from radd.modules.vcs.types import RefStatus, VcsRefType

from .types import PrAction


def plan_push(payload: dict) -> list[PlannedLink]:
    """Branch + commit links from a Forgejo/Gitea push event."""
    repository = payload.get("repository") or {}
    repo_name = repository.get("full_name", "")
    html_url = repository.get("html_url", "")
    branch = (payload.get("ref") or "").removeprefix("refs/heads/")
    planned: list[PlannedLink] = []

    for key in extract_keys(branch):
        planned.append(
            PlannedLink(
                item_key=key,
                ref_type=VcsRefType.BRANCH,
                external_id=branch_external_id(repo_name, branch),
                title=branch,
                url=f"{html_url}/src/branch/{branch}" if html_url else "",
            )
        )

    for commit in payload.get("commits") or []:
        message = commit.get("message") or ""
        for key in extract_keys(message):
            planned.append(
                PlannedLink(
                    item_key=key,
                    ref_type=VcsRefType.COMMIT,
                    external_id=commit_external_id(repo_name, str(commit.get("id", ""))),
                    title=message.splitlines()[0][:300] if message else "commit",
                    url=commit.get("url", ""),
                )
            )
    return planned


def _pr_status(pull_request: dict) -> RefStatus:
    if pull_request.get("merged"):
        return RefStatus.MERGED
    if pull_request.get("state") == RefStatus.CLOSED.value:
        return RefStatus.CLOSED
    return RefStatus.OPEN


def plan_pull_request(payload: dict) -> list[PlannedLink]:
    """Links from a Forgejo/Gitea pull_request event. Keys come from the head
    branch, title, and body; re-deliveries update in place via the stable
    external id `pr:<repo>:<number>`."""
    pull_request = payload.get("pull_request") or {}
    repository = payload.get("repository") or {}
    repo_name = repository.get("full_name", "")
    number = pull_request.get("number", "")
    title = pull_request.get("title") or ""
    head_branch = (pull_request.get("head") or {}).get("ref")
    status = _pr_status(pull_request)
    return [
        PlannedLink(
            item_key=key,
            ref_type=VcsRefType.MERGE_REQUEST,
            external_id=pr_external_id(repo_name, number),
            title=title[:300] or f"#{number}",
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
        merged = _pr_status(payload.get("pull_request") or {}) is RefStatus.MERGED
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
