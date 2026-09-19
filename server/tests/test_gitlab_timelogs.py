"""RADD-1259: time logged on a GitLab merge request mirrored into the linked issue.

GraphQL and REST are stood in for by an httpx.MockTransport carrying the 18.4
shapes verified against Cinesite's GitLab on 2026-09-19 (`Timelog{id, timeSpent,
spentAt, summary, user{id, username, publicEmail}}`, `GET /users/:id` → `email`
for an admin token). The seam's own invariants live in test_time_mirror.py;
this file covers the GitLab-specific half: fetching, paging, the email lookup,
the negative "remove" rows GitLab writes, and the backfill's MR walk.
"""

import json
import uuid
from datetime import date

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.gitlab import backfill, service, timelogs
from radd.modules.gitlab.schemas import ConnectionCreate, RepoCreate
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.timelogging import categories, enablement
from radd.modules.timelogging.models import Worklog
from radd.modules.vcs.models import ItemVcsLink


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def world(db):
    suffix = uuid.uuid4().hex[:6]
    admin = User(email=f"gl-admin-{suffix}@example.com", name="GL Admin", instance_role=InstanceRole.ADMIN.value)
    db.add(admin)
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"GT{suffix[:4].upper()}", name="GitLab time")
    )
    await enablement.set_enabled(db, project.id, True, actor_id=admin.id)
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), actor=admin)
    await categories.ensure_default_categories(db)
    connection = await service.create_connection(
        db, ConnectionCreate(name=f"gl-{suffix}", base_url="https://gitlab.example.com", api_token="glpat-x", webhook_secret="s")
    )
    repo = await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name="pipe/tools"))
    return {"admin": admin, "project": project, "item": item, "key": f"{project.key}-{item.number}", "connection": connection, "repo": repo}


def _timelog(gid: int, seconds: int, username: str, spent_at: str, summary: str = "", user_id: int = 7, public_email: str = ""):
    return {
        "id": f"gid://gitlab/Timelog/{gid}",
        "timeSpent": seconds,
        "spentAt": spent_at,
        "summary": summary,
        "user": {"id": f"gid://gitlab/User/{user_id}", "username": username, "publicEmail": public_email},
    }


def _graphql_pages(pages: list[list[dict]]):
    """A MockTransport answering GraphQL with `pages` in order (cursor = index)
    and `GET /users/:id` with an email for user 7 only."""
    calls = {"graphql": 0, "users": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/graphql"):
            body = json.loads(request.content)
            after = body["variables"].get("after")
            index = int(after) if after else 0
            calls["graphql"] += 1
            nodes = pages[index] if index < len(pages) else []
            has_next = index + 1 < len(pages)
            return httpx.Response(200, json={"data": {"project": {"mergeRequest": {"timelogs": {
                "nodes": nodes,
                "pageInfo": {"hasNextPage": has_next, "endCursor": str(index + 1) if has_next else None},
            }}}}})
        if "/api/v4/users/" in request.url.path:
            user_id = request.url.path.rsplit("/", 1)[-1]
            calls["users"].append(user_id)
            if user_id == "7":
                return httpx.Response(200, json={"id": 7, "username": "hjarrar", "email": "ADMIN_EMAIL"})
            return httpx.Response(200, json={"id": int(user_id), "username": "ghost", "email": None})
        return httpx.Response(404)

    return handler, calls


async def _worklogs(db, item_id):
    return list((await db.execute(select(Worklog).where(Worklog.item_id == item_id).order_by(Worklog.external_id))).scalars())


async def test_reconcile_fetches_pages_looks_up_emails_and_mirrors(db, world):
    admin = world["admin"]
    handler, calls = _graphql_pages([
        [_timelog(1, 5400, "hjarrar", "2026-09-18T00:00:00Z"), _timelog(2, -1800, "hjarrar", "2026-09-18T10:00:00Z")],
        [_timelog(3, 1200, "hjarrar", "2026-09-19T08:30:00Z", summary="pairing"), _timelog(4, 600, "ghost", "2026-09-19T09:00:00Z", user_id=9)],
    ])

    def patched(request):  # the fixture cannot know the admin's email up front
        response = handler(request)
        if b"ADMIN_EMAIL" in response.content:
            return httpx.Response(200, json={"id": 7, "username": "hjarrar", "email": admin.email})
        return response

    report = await timelogs.reconcile_merge_request(
        db, world["connection"], world["repo"],
        project_path="pipe/tools", iid=41, title=f"{world['key']} fix", source_branch="fix", description="",
        transport=httpx.MockTransport(patched),
    )
    assert calls["graphql"] == 2  # both pages walked
    assert calls["users"] == ["7", "9"]  # one lookup per distinct user, publicEmail empty
    assert (report.created, report.pending, report.no_item) == (2, 1, 0)
    rows = await _worklogs(db, world["item"].id)
    by_id = {r.external_id: r for r in rows}
    # The negative row is GitLab's own bookkeeping for a removal — never mirrored.
    assert set(by_id) == {"gid://gitlab/Timelog/1", "gid://gitlab/Timelog/3"}
    # -1800 (entry 2) is GitLab's removal bookkeeping: it TRIMS the most recent
    # live entry before it rather than vanishing (net_entries).
    assert by_id["gid://gitlab/Timelog/1"].time_spent_seconds == 3600
    assert by_id["gid://gitlab/Timelog/1"].worked_on == date(2026, 9, 18)
    assert by_id["gid://gitlab/Timelog/1"].note == f"Logged on !41 {world['key']} fix"
    assert by_id["gid://gitlab/Timelog/3"].note == "pairing"
    assert all(r.author_id == admin.id and r.external_source == "gitlab" and r.external_scope == "pr:pipe/tools:41" for r in rows)
    dev = next(c for c in await categories.list_categories(db) if c.name == "Development")
    assert all(r.category_id == dev.id for r in rows)
    assert report.unmatched_authors == {"ghost"}


async def test_public_email_skips_the_rest_lookup(db, world):
    admin = world["admin"]
    handler, calls = _graphql_pages([[_timelog(11, 60, "hjarrar", "2026-09-18T00:00:00Z", public_email=admin.email)]])
    report = await timelogs.reconcile_merge_request(
        db, world["connection"], world["repo"],
        project_path="pipe/tools", iid=42, title=f"{world['key']} x", source_branch="", description="",
        transport=httpx.MockTransport(handler),
    )
    assert report.created == 1 and calls["users"] == []


def test_spent_on_takes_the_utc_date_as_sent():
    """`/spend 1h 2026-09-18` is stored at midnight UTC on that date; a
    zone-shifted reading would move it to the 17th west of Greenwich."""
    assert timelogs.spent_on("2026-09-18T12:00:00Z") == date(2026, 9, 18)  # a dated /spend, as 18.4 stores it
    assert timelogs.spent_on("2026-09-18T23:59:59+00:00") == date(2026, 9, 18)


def test_net_entries_folds_gitlab_removals_lifo():
    """Found live on 2026-09-19: `reset_spent_time` left every positive row in
    place and appended -9300. Dropping negatives mirrored 2h35m onto an MR GitLab
    reported as 0."""
    nodes = [
        _timelog(1, 5400, "a", "2026-09-19T14:10:00Z"),
        _timelog(2, 1200, "a", "2026-09-19T14:14:00Z"),
        _timelog(3, 2700, "a", "2026-09-18T00:00:00Z"),  # dated earlier, logged later
        _timelog(4, -9300, "a", "2026-09-19T14:20:00Z"),  # the reset
        _timelog(5, 5400, "a", "2026-09-18T00:00:00Z"),  # re-added, dated
        _timelog(6, 1200, "a", "2026-09-19T14:25:00Z"),
    ]
    live = timelogs.net_entries(nodes)
    assert [(n["id"].split("/")[-1], n["timeSpent"]) for n in live] == [("5", 5400), ("6", 1200)]
    assert sum(n["timeSpent"] for n in live) == 6600  # GitLab's totalTimeSpent
    # A partial negative (`add_spent_time -30m`) trims the most recent entry.
    partial = timelogs.net_entries([_timelog(1, 3600, "a", "2026-09-01T00:00:00Z"), _timelog(2, -1800, "a", "2026-09-01T01:00:00Z")])
    assert [(n["id"].split("/")[-1], n["timeSpent"]) for n in partial] == [("1", 1800)]
    # A negative larger than everything before it leaves nothing, and never goes below zero.
    assert timelogs.net_entries([_timelog(1, 60, "a", "2026-09-01T00:00:00Z"), _timelog(2, -600, "a", "2026-09-01T01:00:00Z")]) == []


def test_to_source_entries_drops_blanks_and_folds():
    entries = timelogs.to_source_entries(
        [
            _timelog(1, 60, "a", "2026-09-01T00:00:00Z"),
            _timelog(2, -60, "a", "2026-09-01T00:00:01Z"),
            _timelog(3, 120, "a", "2026-09-02T00:00:00Z"),
            {"id": "", "timeSpent": 60, "spentAt": "2026-09-01T00:00:00Z", "user": {"username": "a"}},
            {"id": "gid://gitlab/Timelog/9", "timeSpent": 60, "spentAt": "2026-09-01T00:00:00Z", "user": {}},
        ],
        {"a": "a@example.com"},
    )
    assert [(e.external_id, e.seconds, e.author_email) for e in entries] == [("gid://gitlab/Timelog/3", 120, "a@example.com")]


def test_real_delivery_fixture_reads_as_a_time_change():
    """A sanitised `merge_request` delivery recorded from GitLab 18.4.1 EE on
    2026-09-19 (the REST `add_spent_time` of 1h30m — the first time on the MR)."""
    import json
    from pathlib import Path

    from radd.modules.gitlab import parsing

    payload = json.loads((Path(__file__).parent / "fixtures" / "gitlab_mr_time_change.json").read_text())
    assert payload["object_kind"] == "merge_request"
    assert parsing.time_spent_changed(payload)
    assert payload["changes"]["total_time_spent"] == {"previous": 0, "current": 5400}
    assert payload["changes"]["time_change"]["current"] == 5400
    links, merged = parsing.plan_merge_request(payload)
    assert merged is False and links and links[0].external_id.startswith("pr:")
    assert parsing.project_path(payload) == payload["project"]["path_with_namespace"]


async def test_backfill_walks_merge_requests_and_imports_their_time_once(db, world):
    """The historical import: MRs that report time have their entries mirrored;
    the second run adds nothing."""
    admin = world["admin"]
    key = world["key"]
    graphql, _ = _graphql_pages([[_timelog(21, 3600, "hjarrar", "2026-09-10T00:00:00Z", public_email=admin.email)]])

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api/graphql"):
            return graphql(request)
        if path.endswith("/repository/branches"):
            return httpx.Response(200, json=[{"name": f"{key}-branch", "web_url": "https://gitlab.example.com/pipe/tools/-/tree/x"}])
        if path.endswith("/merge_requests"):
            return httpx.Response(200, json=[
                {"iid": 5, "title": f"{key} timed", "source_branch": "t", "description": "", "state": "merged",
                 "web_url": "https://gitlab.example.com/pipe/tools/-/merge_requests/5", "time_stats": {"total_time_spent": 3600}},
                {"iid": 6, "title": f"{key} untimed", "source_branch": "u", "description": "", "state": "opened",
                 "web_url": "https://gitlab.example.com/pipe/tools/-/merge_requests/6", "time_stats": {"total_time_spent": 0}},
            ])
        if path.endswith("/repository/commits"):
            return httpx.Response(200, json=[{"id": "c" * 40, "message": f"[{key}] a commit", "web_url": "https://gitlab.example.com/pipe/tools/-/commit/c"}])
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    first = await backfill.run(db, world["connection"], world["repo"], transport=transport)
    assert (first.branches, first.merge_requests, first.commits, first.linked) == (1, 2, 1, 4)
    assert first.timed_merge_requests == 1 and first.worklogs.get("created") == 1

    second = await backfill.run(db, world["connection"], world["repo"], transport=transport)
    assert second.linked == 4 and second.worklogs.get("created", 0) == 0 and second.worklogs.get("unchanged") == 1

    links = list((await db.execute(select(ItemVcsLink).where(ItemVcsLink.item_id == world["item"].id))).scalars())
    assert sorted(link.external_id for link in links) == sorted([
        f"branch:pipe/tools:{key}-branch", "pr:pipe/tools:5", "pr:pipe/tools:6", "commit:pipe/tools:" + "c" * 40,
    ])
    rows = await _worklogs(db, world["item"].id)
    assert len(rows) == 1 and rows[0].external_scope == "pr:pipe/tools:5" and rows[0].time_spent_seconds == 3600


def test_project_api_path_encodes_the_namespace():
    assert backfill.project_api_path("group/sub/project") == "/projects/group%2Fsub%2Fproject"
