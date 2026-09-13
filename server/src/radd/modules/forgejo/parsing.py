"""Pure Forgejo/Gitea webhook → planned vcs-link parsing (spec 47) — tested in
tests/test_connectors.py. No I/O: key resolution and writes happen in the router.

Deliberately mirrors gitlab/parsing.py (same key grammar, same PlannedLink shape)
without importing it — the connectors are independent modules and either may be
disabled without the other. External ids come from `vcs.ids` (RADD-1124): the
webhook, the backfill and the CI stamp must spell a ref identically, and a
commit written here as its bare SHA was invisible to both of the others.
"""

import re
from dataclasses import dataclass

from radd.modules.vcs.ids import branch_external_id, commit_external_id, pr_external_id
from radd.modules.vcs.types import VcsRefType

from .types import PrStatus

# An item key referenced in text: TD-123 (project keys are 1-10 alnum starting
# with a letter). Word-bounded so sha1-2abc doesn't match. Same rules as gitlab.
KEY_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]{0,9}-\d+)\b")


@dataclass(frozen=True)
class PlannedLink:
    item_key: str  # upper-cased "TD-123"
    ref_type: VcsRefType
    external_id: str
    title: str
    url: str
    status: str = ""


def extract_keys(*texts: str | None) -> list[str]:
    """Upper-cased, deduped, order-preserving item keys found in the texts."""
    seen: list[str] = []
    for text in texts:
        for match in KEY_RE.finditer(text or ""):
            key = match.group(1).upper()
            if key not in seen:
                seen.append(key)
    return seen


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


def _pr_status(pull_request: dict) -> PrStatus:
    if pull_request.get("merged"):
        return PrStatus.MERGED
    if pull_request.get("state") == PrStatus.CLOSED.value:
        return PrStatus.CLOSED
    return PrStatus.OPEN


def plan_pull_request(payload: dict) -> tuple[list[PlannedLink], bool]:
    """(links, merged?) from a Forgejo/Gitea pull_request event. Keys come from
    the head branch, title, and body; re-deliveries update in place via the
    stable external id `pr:<repo>:<number>`."""
    pull_request = payload.get("pull_request") or {}
    repository = payload.get("repository") or {}
    repo_name = repository.get("full_name", "")
    number = pull_request.get("number", "")
    title = pull_request.get("title") or ""
    head_branch = (pull_request.get("head") or {}).get("ref")
    status = _pr_status(pull_request)
    links = [
        PlannedLink(
            item_key=key,
            ref_type=VcsRefType.MERGE_REQUEST,
            external_id=pr_external_id(repo_name, number),
            title=title[:300] or f"#{number}",
            url=pull_request.get("html_url", ""),
            status=status.value,
        )
        for key in extract_keys(head_branch, title, pull_request.get("body"))
    ]
    return links, status is PrStatus.MERGED
