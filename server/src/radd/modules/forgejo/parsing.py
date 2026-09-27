"""Pure Forgejo/Gitea webhook → planned vcs-link parsing. No I/O; external ids come
from `vcs.ids`. A pull_request or release delivery is GitHub's shape, parsed by
`vcs.connector_kit.github_shape`."""

from radd.modules.vcs.ids import branch_external_id, commit_external_id
from radd.modules.vcs.keys import PlannedLink, extract_keys
from radd.modules.vcs.types import VcsRefType


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
