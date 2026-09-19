"""GitLab webhook parsing core (spec 31, rebuilt RADD-1253/1254).

Pure tests of key extraction and event → planned-link mapping — the piece the
connector's correctness hangs on. Since RADD-1254 every external id is the
canonical `vcs/ids.py` spelling, so a backfill after a webhook lands on the same
row. The endpoint (token check, upsert, merge transition) is exercised live in
test_gitlab_connections.py.
"""

from radd.modules.gitlab.parsing import (
    extract_keys,
    mr_status,
    plan_merge_request,
    plan_push,
    time_spent_changed,
    version_from_tag,
)
from radd.modules.gitlab.types import MrStatus
from radd.modules.vcs.types import VcsRefType


def test_extract_keys_bounded_cased_deduped():
    assert extract_keys("td-12 fixes TD-12 and DEV-3, sha1-2abc") == ["TD-12", "DEV-3"]
    assert extract_keys("feature/td-99-fix-farm") == ["TD-99"]
    assert extract_keys(None, "", "no keys here") == []


PUSH = {
    "object_kind": "push",
    "ref": "refs/heads/td-7-farm-fix",
    "project": {"path_with_namespace": "Pipe/Tools", "web_url": "https://git/pipe/tools"},
    "commits": [
        {"id": "abc123", "message": "TD-7: restart daemon\n\nlong body", "url": "https://git/c/abc123"},
        {"id": "def456", "message": "unrelated cleanup", "url": "https://git/c/def456"},
    ],
}


def test_plan_push_links_branch_and_commits_with_canonical_ids():
    planned = plan_push(PUSH)
    assert [(p.item_key, p.ref_type) for p in planned] == [
        ("TD-7", VcsRefType.BRANCH),
        ("TD-7", VcsRefType.COMMIT),
    ]
    branch, commit = planned
    # RADD-1254: the repository segment is LOWERCASED and a commit is never a bare SHA.
    assert branch.external_id == "branch:pipe/tools:td-7-farm-fix"
    assert branch.url == "https://git/pipe/tools/-/tree/td-7-farm-fix"
    assert commit.title == "TD-7: restart daemon"
    assert commit.external_id == "commit:pipe/tools:abc123"


def test_plan_push_ignores_tag_refs():
    assert plan_push({**PUSH, "ref": "refs/tags/v1.2.3"}) == []


def test_plan_merge_request_links_and_merge_flag():
    payload = {
        "object_kind": "merge_request",
        "project": {"path_with_namespace": "pipe/tools"},
        "object_attributes": {
            "iid": 41,
            "title": "Fix render farm (TD-7)",
            "description": "Also touches DEV-3.",
            "source_branch": "td-7-farm-fix",
            "state": "merged",
            "action": "merge",
            "url": "https://git/pipe/tools/-/merge_requests/41",
        },
    }
    links, merged = plan_merge_request(payload)
    assert merged is True
    assert [link.item_key for link in links] == ["TD-7", "DEV-3"]
    assert all(link.ref_type is VcsRefType.MERGE_REQUEST for link in links)
    # The other hosts' pull requests spell `pr:`; the ref TYPE says it is an MR.
    assert links[0].external_id == "pr:pipe/tools:41"
    assert links[0].status == "merged"
    assert links[0].title == "Fix render farm (TD-7) (!41)"


def test_plan_merge_request_open_is_not_merged():
    payload = {
        "object_attributes": {"iid": 2, "title": "TD-1 wip", "state": "opened", "action": "open"},
        "project": {},
    }
    links, merged = plan_merge_request(payload)
    assert merged is False and len(links) == 1 and links[0].status == "open"


def test_mr_status_maps_gitlab_states():
    assert mr_status({"state": "opened"}) is MrStatus.OPEN
    assert mr_status({"state": "locked"}) is MrStatus.OPEN
    assert mr_status({"state": "closed"}) is MrStatus.CLOSED
    assert mr_status({"state": "merged"}) is MrStatus.MERGED
    assert mr_status({"state": "opened", "action": "merge"}) is MrStatus.MERGED


def test_time_spent_changed_reads_the_changes_object():
    """RADD-1259: no timelog webhook exists; the MR delivery that added or
    removed time is the one whose `changes` carries `total_time_spent`."""
    assert time_spent_changed({"changes": {"total_time_spent": {"previous": 0, "current": 3600}}})
    assert time_spent_changed({"changes": {"time_change": {"previous": None, "current": 1800}}})
    assert not time_spent_changed({"changes": {"title": {"previous": "a", "current": "b"}}})
    assert not time_spent_changed({"object_attributes": {"iid": 1}})


def test_version_from_tag_strips_only_a_leading_v():
    assert version_from_tag("v0.6.1") == "0.6.1"
    assert version_from_tag("0.6.1") == "0.6.1"
    assert version_from_tag("valentine") == "valentine"
