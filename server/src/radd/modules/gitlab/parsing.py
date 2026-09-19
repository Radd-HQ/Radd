"""Pure GitLab webhook → planned vcs-link parsing (spec 31, rebuilt RADD-1253/1254).
No I/O: key resolution and writes happen in the router.

Deliberately mirrors forgejo/parsing.py and github/parsing.py (same key grammar,
same PlannedLink shape) without importing them — the connectors are independent
modules and any may be disabled without the others.

RADD-1254: every external id is spelled by `vcs/ids.py` — a commit is
`commit:<namespace/project>:<sha>`, never the bare SHA the spec-31 receiver
wrote, and a merge request is `pr:<namespace/project>:<iid>` like the other
hosts' pull requests (the ref TYPE says which it is). That is what lets the
backfill, the webhook and a CI stamp land on ONE row.
"""

import re
from dataclasses import dataclass

from radd.modules.vcs.ids import branch_external_id, commit_external_id, pr_external_id
from radd.modules.vcs.types import VcsRefType

from .types import MrStatus

# An item key referenced in text: TD-123 (project keys are 1-10 alnum starting
# with a letter). Word-bounded so sha1-2abc doesn't match.
KEY_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]{0,9}-\d+)\b")

#: GitLab sends at most this many commits in one push payload; a bigger push
#: reports `total_commits_count` above it and the rest is the backfill's job.
PUSH_COMMIT_LIMIT = 20


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


def project_path(payload: dict) -> str:
    return str((payload.get("project") or {}).get("path_with_namespace") or "").strip("/")


def plan_push(payload: dict) -> list[PlannedLink]:
    """Branch + commit links from a GitLab push event. A tag push arrives as its
    own `object_kind` and plans nothing here."""
    project = payload.get("project") or {}
    repo = project_path(payload)
    web_url = str(project.get("web_url") or "")
    ref = str(payload.get("ref") or "")
    if not ref.startswith("refs/heads/"):
        return []
    branch = ref.removeprefix("refs/heads/")
    planned: list[PlannedLink] = []

    for key in extract_keys(branch):
        planned.append(
            PlannedLink(
                item_key=key,
                ref_type=VcsRefType.BRANCH,
                external_id=branch_external_id(repo, branch),
                title=branch,
                url=f"{web_url}/-/tree/{branch}" if web_url else "",
            )
        )

    for commit in payload.get("commits") or []:
        message = commit.get("message") or ""
        sha = str(commit.get("id") or "")
        for key in extract_keys(message):
            planned.append(
                PlannedLink(
                    item_key=key,
                    ref_type=VcsRefType.COMMIT,
                    external_id=commit_external_id(repo, sha),
                    title=message.splitlines()[0][:300] if message else "commit",
                    url=str(commit.get("url") or (f"{web_url}/-/commit/{sha}" if web_url else "")),
                )
            )
    return planned


def mr_status(attributes: dict) -> MrStatus:
    """`opened`/`locked` → open, `merged` → merged, `closed` → closed."""
    # GitLab's `state` values `merged`/`closed` spell the same as our statuses.
    state = str(attributes.get("state") or "")
    if state == MrStatus.MERGED or attributes.get("action") == "merge":
        return MrStatus.MERGED
    if state == MrStatus.CLOSED:
        return MrStatus.CLOSED
    return MrStatus.OPEN


def mr_title(attributes: dict) -> str:
    iid = attributes.get("iid", "")
    title = str(attributes.get("title") or "")
    return f"{title[:280]} (!{iid})".strip() if title else f"!{iid}"


def plan_merge_request(payload: dict) -> tuple[list[PlannedLink], bool]:
    """(links, merged?) from a merge_request event. Keys come from the source
    branch, title and description; re-deliveries update in place via the stable
    external id `pr:<project>:<iid>`."""
    attributes = payload.get("object_attributes") or {}
    repo = project_path(payload)
    status = mr_status(attributes)
    links = [
        PlannedLink(
            item_key=key,
            ref_type=VcsRefType.MERGE_REQUEST,
            external_id=pr_external_id(repo, attributes.get("iid", "")),
            title=mr_title(attributes),
            url=str(attributes.get("url") or ""),
            status=status.value,
        )
        for key in extract_keys(
            attributes.get("source_branch"), attributes.get("title"), attributes.get("description")
        )
    ]
    return links, status is MrStatus.MERGED


def time_spent_changed(payload: dict) -> bool:
    """Whether this merge_request delivery reports time added or removed
    (RADD-1259). GitLab has no timelog webhook; the MR event's `changes` object
    carries `total_time_spent {previous, current}` (and `time_change`) on the
    delivery that did it — the trigger to go and fetch the per-user entries."""
    changes = payload.get("changes") or {}
    if "total_time_spent" in changes or "time_change" in changes:
        return True
    return bool((payload.get("object_attributes") or {}).get("time_change"))


def version_from_tag(tag: str) -> str:
    """`v0.6.1` -> `0.6.1` (RADD-707): tags are `vX.Y.Z` by convention while
    every release recorded in the tracker is bare."""
    tag = tag.strip()
    return tag[1:] if len(tag) > 1 and tag[0] in "vV" and tag[1].isdigit() else tag
