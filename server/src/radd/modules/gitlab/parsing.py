"""Pure GitLab webhook → planned vcs-link parsing. No I/O; external ids come from
`vcs.ids` (a merge request is `pr:<namespace/project>:<iid>` like the other hosts'
pull requests — the ref TYPE says which)."""

from dataclasses import dataclass

from radd.modules.vcs.ids import branch_external_id, commit_external_id, pr_external_id
from radd.modules.vcs.keys import PlannedLink, extract_keys
from radd.modules.vcs.triggers import COMMITS_CHANGE, RefAction, diff_entries
from radd.modules.vcs.types import RefStatus, VcsRefType

from .types import MrAction


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


def mr_status(attributes: dict) -> RefStatus:
    """`opened`/`locked` → open, `merged` → merged, `closed` → closed."""
    # GitLab's `state` values `merged`/`closed` spell the same as our statuses.
    state = str(attributes.get("state") or "")
    if state == RefStatus.MERGED or attributes.get("action") == MrAction.MERGE:
        return RefStatus.MERGED
    if state == RefStatus.CLOSED:
        return RefStatus.CLOSED
    return RefStatus.OPEN


def mr_title(attributes: dict) -> str:
    iid = attributes.get("iid", "")
    title = str(attributes.get("title") or "")
    return f"{title[:280]} (!{iid})".strip() if title else f"!{iid}"


def plan_merge_request(payload: dict) -> list[PlannedLink]:
    """Links from a merge_request event. Keys come from the source branch, title
    and description; re-deliveries update in place via the stable external id
    `pr:<project>:<iid>`."""
    attributes = payload.get("object_attributes") or {}
    repo = project_path(payload)
    status = mr_status(attributes)
    return [
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


_MR_ACTIONS = {
    MrAction.OPEN: RefAction.OPENED,
    MrAction.REOPEN: RefAction.OPENED,
    MrAction.MERGE: RefAction.MERGED,
    MrAction.CLOSE: RefAction.CLOSED,
    MrAction.UPDATE: RefAction.UPDATED,
}


def mr_changes(payload: dict) -> list[dict]:
    """What an `update` delivery changed (RADD-1330), as the kernel diff: GitLab's
    `changes` object gives `{previous, current}` per field, and `oldrev` says new
    commits were pushed (the new head is `last_commit.id`)."""
    triples = [
        (name, (value or {}).get("previous"), (value or {}).get("current"))
        for name, value in (payload.get("changes") or {}).items()
        if isinstance(value, dict)
    ]
    attributes = payload.get("object_attributes") or {}
    if attributes.get("oldrev"):
        head = (attributes.get("last_commit") or {}).get("id") or "new"
        triples.append((COMMITS_CHANGE, attributes["oldrev"], head))
    return diff_entries(triples)


def mr_action(payload: dict) -> RefAction | None:
    """What the delivery DID, by `action` — never by state, which every later edit
    repeats (RADD-1309). None = no trigger (an approval, a time change, …)."""
    action = str((payload.get("object_attributes") or {}).get("action") or "")
    return _MR_ACTIONS.get(action)


def mr_ref_extra(payload: dict) -> dict[str, object]:
    """The `ref` fields a trigger carries that the link row does not store."""
    attributes = payload.get("object_attributes") or {}
    return {
        "number": attributes.get("iid"),
        "source_branch": attributes.get("source_branch"),
        "target_branch": attributes.get("target_branch"),
    }


def time_spent_changed(payload: dict) -> bool:
    """Whether this merge_request delivery reports time added or removed
    (RADD-1259). GitLab has no timelog webhook; the MR event's `changes` object
    carries `total_time_spent {previous, current}` (and `time_change`) on the
    delivery that did it — the trigger to go and fetch the per-user entries."""
    changes = payload.get("changes") or {}
    if "total_time_spent" in changes or "time_change" in changes:
        return True
    return bool((payload.get("object_attributes") or {}).get("time_change"))


@dataclass(frozen=True)
class RefUpdate:
    """What a pipeline or deployment delivery is about (RADD-1255): the ref ids
    it names, and the outcome it reports."""

    repo: str
    external_ids: tuple[str, ...]
    status: str
    url: str
    ref: str = ""
    sha: str = ""
    environment: str = ""
    run_id: int | None = None
    updated_at: str = ""


def _ref_ids(repo: str, ref: str, sha: str, *, is_tag: bool, mr_iid: object = None) -> tuple[str, ...]:
    ids: list[str] = []
    if ref and not is_tag:
        ids.append(branch_external_id(repo, ref))
    if sha:
        ids.append(commit_external_id(repo, sha))
    if mr_iid not in (None, ""):
        ids.append(pr_external_id(repo, mr_iid))
    return tuple(ids)


def plan_pipeline(payload: dict) -> RefUpdate | None:
    """A `pipeline` delivery: `object_attributes.{ref, sha, status, url, tag}`,
    and `merge_request.iid` for an MR pipeline. The branch, the commit and the MR
    are all "this ref" — the badge on each is the latest run's."""
    attributes = payload.get("object_attributes") or {}
    repo = project_path(payload)
    ref, sha = str(attributes.get("ref") or ""), str(attributes.get("sha") or "")
    if not repo or not (ref or sha):
        return None
    mr = payload.get("merge_request") or {}
    web_url = str((payload.get("project") or {}).get("web_url") or "")
    url = str(attributes.get("url") or (f"{web_url}/-/pipelines/{attributes.get('id')}" if web_url else ""))
    try:
        run_id = int(attributes.get("id"))
        if not 0 < run_id < 2**63:
            run_id = None
    except (TypeError, ValueError):
        run_id = None
    return RefUpdate(
        repo=repo,
        external_ids=_ref_ids(repo, ref, sha, is_tag=bool(attributes.get("tag")), mr_iid=mr.get("iid")),
        status=str(attributes.get("status") or ""),
        url=url,
        ref=ref,
        sha=sha,
        run_id=run_id,
        updated_at=str(attributes.get("updated_at") or attributes.get("finished_at") or attributes.get("started_at") or ""),
    )


def plan_deployment(payload: dict) -> RefUpdate | None:
    """A `deployment` delivery: `status`, `environment`, `ref`, `sha`, and the
    environment's own URL (`environment_external_url`) or the job's."""
    repo = project_path(payload)
    ref, sha = str(payload.get("ref") or ""), str(payload.get("sha") or "")
    if not repo or not (ref or sha):
        return None
    return RefUpdate(
        repo=repo,
        external_ids=_ref_ids(repo, ref, sha, is_tag=bool(payload.get("tag"))),
        status=str(payload.get("status") or ""),
        url=str(payload.get("environment_external_url") or payload.get("deployable_url") or ""),
        ref=ref,
        sha=sha,
        environment=str(payload.get("environment") or ""),
    )
