"""GitLab webhook parsing core (spec 31).

Pure tests of key extraction and event → planned-link mapping — the piece the
connector's correctness hangs on. The endpoint (secret check, upsert, merge
transition) is exercised live against an isolated DB.
"""

from radd.modules.gitlab.parsing import extract_keys, plan_merge_request, plan_push
from radd.modules.vcs.types import VcsRefType


def test_extract_keys_bounded_cased_deduped():
    assert extract_keys("td-12 fixes TD-12 and DEV-3, sha1-2abc") == ["TD-12", "DEV-3"]
    assert extract_keys("feature/td-99-fix-farm") == ["TD-99"]
    assert extract_keys(None, "", "no keys here") == []


def test_plan_push_links_branch_and_commits():
    payload = {
        "object_kind": "push",
        "ref": "refs/heads/td-7-farm-fix",
        "project": {"path_with_namespace": "pipe/tools", "web_url": "https://git/pipe/tools"},
        "commits": [
            {"id": "abc123", "message": "TD-7: restart daemon\n\nlong body", "url": "https://git/c/abc123"},
            {"id": "def456", "message": "unrelated cleanup", "url": "https://git/c/def456"},
        ],
    }
    planned = plan_push(payload)
    assert [(p.item_key, p.ref_type) for p in planned] == [
        ("TD-7", VcsRefType.BRANCH),
        ("TD-7", VcsRefType.COMMIT),
    ]
    branch, commit = planned
    assert branch.external_id == "branch:pipe/tools:td-7-farm-fix"
    assert branch.url == "https://git/pipe/tools/-/tree/td-7-farm-fix"
    assert commit.title == "TD-7: restart daemon"
    assert commit.external_id == "abc123"


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
    assert links[0].external_id == "mr:pipe/tools:41"
    assert links[0].status == "merged"


def test_plan_merge_request_open_is_not_merged():
    payload = {
        "object_attributes": {"iid": 2, "title": "TD-1 wip", "state": "opened", "action": "open"},
        "project": {},
    }
    links, merged = plan_merge_request(payload)
    assert merged is False and len(links) == 1
