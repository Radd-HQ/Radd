"""GitHub's pull_request and release webhook shapes, which Forgejo and Gitea emit too
(RADD-1435): one parser for both hosts. Pure; external ids come from `vcs.ids`."""

from dataclasses import dataclass
from enum import StrEnum

from ..ids import pr_external_id
from ..keys import PlannedLink, extract_keys
from ..triggers import RefAction
from ..types import RefStatus, VcsRefType
from .changes import UNSENT, MrChangeField, diff_entries, sent


class PrAction(StrEnum):
    """Pull-request `action` values that fire a trigger. A merge is `closed` with
    the pull request merged."""

    OPENED = "opened"
    REOPENED = "reopened"
    CLOSED = "closed"
    EDITED = "edited"  # RADD-1330: fires "updated"
    # New commits pushed: "updated" with a `commits` change. GitHub spells it
    # `synchronize`, Forgejo/Gitea `synchronized`.
    SYNCHRONIZE = "synchronize"
    SYNCHRONIZED = "synchronized"


_NEW_COMMITS = frozenset({PrAction.SYNCHRONIZE, PrAction.SYNCHRONIZED})


class ReleaseAction(StrEnum):
    """Only `published` publishes — a draft, an edit or a deletion must not."""

    PUBLISHED = "published"


def repo_full_name(payload: dict) -> str:
    """The `owner/repo` a delivery names, as the host spells it."""
    return str((payload.get("repository") or {}).get("full_name") or "")


def pr_status(pull_request: dict) -> RefStatus:
    # GitHub sometimes omits `merged` on re-deliveries but always carries `merged_at`.
    if pull_request.get("merged") or pull_request.get("merged_at"):
        return RefStatus.MERGED
    if pull_request.get("state") == RefStatus.CLOSED.value:
        return RefStatus.CLOSED
    return RefStatus.OPEN


def pr_title(pull_request: dict) -> str:
    number = pull_request.get("number", "")
    title = str(pull_request.get("title") or "")
    return f"{title[:280]} (#{number})".strip() if title else f"#{number}"


def plan_pull_request(payload: dict) -> list[PlannedLink]:
    """Links from a pull_request delivery. Keys come from the head branch, title
    and body; re-deliveries (and the backfill) update in place via the stable
    external id `pr:<repo>:<number>`."""
    pull_request = payload.get("pull_request") or {}
    title = pull_request.get("title") or ""
    head_branch = (pull_request.get("head") or {}).get("ref")
    return [
        PlannedLink(
            item_key=key,
            ref_type=VcsRefType.PULL_REQUEST,
            external_id=pr_external_id(repo_full_name(payload), pull_request.get("number", "")),
            title=pr_title(pull_request),
            url=pull_request.get("html_url", ""),
            status=pr_status(pull_request).value,
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
    if action == PrAction.EDITED or action in _NEW_COMMITS:
        return RefAction.UPDATED
    return None


#: The `changes` keys an `edited` delivery may carry that fire "updated"
#: (RADD-1451): GitHub spells the body `body` and a base-branch change `base`
#: (`changes.base.ref.from`); Forgejo spells the latter `ref`. Labels, assignees
#: and reviewers arrive as their own actions on these hosts, which fire nothing.
_EDITED_FIELDS: dict[str, MrChangeField] = {
    "title": MrChangeField.TITLE,
    "body": MrChangeField.DESCRIPTION,
    "base": MrChangeField.TARGET_BRANCH,
    "ref": MrChangeField.TARGET_BRANCH,
}


def _previous(name: str, value: dict) -> object:
    """The old side of an `edited` change: `{from}`, nested under `ref` for `base`."""
    if name == "base":
        value = value.get("ref") if isinstance(value.get("ref"), dict) else {}
    return value["from"] if "from" in value else UNSENT


def _current(field: MrChangeField, pull: dict) -> object:
    """The new side, read from the pull request itself."""
    if field is MrChangeField.TITLE:
        return pull["title"] if "title" in pull else UNSENT
    if field is MrChangeField.DESCRIPTION:
        return pull["body"] if "body" in pull else UNSENT
    base = pull.get("base") if isinstance(pull.get("base"), dict) else {}
    return base["ref"] if "ref" in base else UNSENT


def pr_changes(payload: dict) -> list[dict]:
    """What an update changed (RADD-1330), as the kernel diff, for the fields in
    `MrChangeField` only (RADD-1451): an `edited` delivery's `changes` gives the
    old value and the pull request the new one; new commits are `before` →
    `after` when the host sends them, else the request's head sha alone."""
    pull = payload.get("pull_request") or {}
    if str(payload.get("action") or "") in _NEW_COMMITS:
        head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
        after = sent(payload.get("after"))
        if after is UNSENT:
            after = sent(head.get("sha"))
        return diff_entries([(MrChangeField.COMMITS, sent(payload.get("before")), after)])
    return diff_entries(
        (field, _previous(name, value), _current(field, pull))
        for name, value in (payload.get("changes") or {}).items()
        if (field := _EDITED_FIELDS.get(name)) is not None and isinstance(value, dict)
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
class PublishedRelease:
    tag: str
    name: str
    notes: str
    url: str


def published_release(payload: dict) -> PublishedRelease | None:
    """A `release` delivery that PUBLISHED something; None for a draft, an edit or
    a deletion."""
    release = payload.get("release") or {}
    if str(payload.get("action") or "") != ReleaseAction.PUBLISHED or release.get("draft"):
        return None
    return PublishedRelease(
        tag=str(release.get("tag_name") or ""),
        name=str(release.get("name") or ""),
        notes=str(release.get("body") or ""),
        url=str(release.get("html_url") or ""),
    )
