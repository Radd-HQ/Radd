"""Pure GitLab webhook → planned vcs-link parsing (spec 31) — tested in
tests/test_gitlab.py. No I/O: key resolution and writes happen in the router."""

import re
from dataclasses import dataclass

from radd.modules.vcs.types import VcsRefType

# An item key referenced in text: TD-123 (project keys are 1-10 alnum starting
# with a letter). Word-bounded so sha1-2abc doesn't match.
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
    """Branch + commit links from a GitLab push event."""
    project = payload.get("project") or {}
    project_path = project.get("path_with_namespace", "")
    web_url = project.get("web_url", "")
    branch = (payload.get("ref") or "").removeprefix("refs/heads/")
    planned: list[PlannedLink] = []

    for key in extract_keys(branch):
        planned.append(
            PlannedLink(
                item_key=key,
                ref_type=VcsRefType.BRANCH,
                external_id=f"branch:{project_path}:{branch}",
                title=branch,
                url=f"{web_url}/-/tree/{branch}" if web_url else "",
            )
        )

    for commit in payload.get("commits") or []:
        message = commit.get("message") or ""
        for key in extract_keys(message):
            planned.append(
                PlannedLink(
                    item_key=key,
                    ref_type=VcsRefType.COMMIT,
                    external_id=str(commit.get("id", "")),
                    title=message.splitlines()[0][:300] if message else "commit",
                    url=commit.get("url", ""),
                )
            )
    return planned


def plan_merge_request(payload: dict) -> tuple[list[PlannedLink], bool]:
    """(links, merged?) from a GitLab merge_request event. Keys come from the
    source branch, title, and description; re-deliveries update in place."""
    attributes = payload.get("object_attributes") or {}
    project = payload.get("project") or {}
    project_path = project.get("path_with_namespace", "")
    state = attributes.get("state", "")
    title = attributes.get("title") or ""
    keys = extract_keys(attributes.get("source_branch"), title, attributes.get("description"))
    links = [
        PlannedLink(
            item_key=key,
            ref_type=VcsRefType.MERGE_REQUEST,
            external_id=f"mr:{project_path}:{attributes.get('iid', '')}",
            title=title[:300] or f"!{attributes.get('iid', '')}",
            url=attributes.get("url", ""),
            status=state,
        )
        for key in keys
    ]
    merged = attributes.get("action") == "merge" or state == "merged"
    return links, merged
