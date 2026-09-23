"""Bounded audience references retain policy and effective roster count parity."""

import uuid

import httpx
import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.exceptions import ConflictError
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.comments import service as comments
from radd.modules.comments.models import Comment, CommentVisibilityTeam
from radd.modules.groups.models import Group, GroupMember, GroupParent
from radd.modules.teams import service as teams
from radd.modules.teams.models import Team, TeamMember
from radd.modules.auth.types import LoginMethod


@pytest.fixture
async def world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        prefix = uuid.uuid4().hex
        actor = User(
            name="Audience operator", email=prefix + "@test.invalid", instance_role="admin"
        )
        catalog = [Team(name=f"{prefix} Team {i:03}") for i in range(126)]
        people = [
            User(name=f"Person {i}", email=f"{prefix}-{i}@test.invalid", active=i != 4)
            for i in range(5)
        ]
        groups = [Group(name=f"Group {i}", dn=f"{prefix}-{i}") for i in range(5)]
        db.add_all([actor, *catalog, *people, *groups])
        await db.flush()
        db.add_all([GroupMember(group_id=g.id, user_id=u.id) for g, u in zip(groups, people)])
        db.add_all(
            [
                GroupParent(parent_id=groups[a].id, child_id=groups[b].id)
                for a, b in [(0, 1), (0, 2), (1, 3), (2, 3), (3, 0), (3, 4)]
            ]
        )
        for index, team in enumerate(catalog[:125]):
            db.add_all([TeamMember(team_id=team.id, group_id=groups[i].id) for i in (0, 2)])
            db.add(TeamMember(team_id=team.id, user_id=people[index % 5].id))
        await db.flush()
        yield db, engine, actor, catalog, prefix
        await db.rollback()
    await engine.dispose()


@pytest.mark.parametrize("depth", [0, 1, 2, 4])
async def test_batched_counts_match_rosters_with_shared_cyclic_diamonds(world, monkeypatch, depth):
    db, engine, actor, catalog, prefix = world
    monkeypatch.setattr(settings, "group_nesting_max_depth", depth)
    requested = [team.id for team in [*catalog[:49], catalog[-1]]]
    sql = []

    def record(conn, cursor, statement, parameters, context, executemany):
        sql.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        counts = await teams.member_counts(db, requested)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    assert len(sql) == 1 and "WITH RECURSIVE" in sql[0]
    assert "users.email" not in sql[0] and "users.name" not in sql[0]
    for team_id in requested:
        assert counts.get(team_id, 0) == len(await teams.list_team_members(db, team_id))
    assert catalog[-1].id not in counts  # empty roster
    if depth == 4:
        assert set(counts.values()) == {5}  # inactive member retained, overlaps counted once
    assert await teams.member_counts(db, []) == {}


async def test_reference_http_windows_lean_payload_and_credential_policy(world):
    db, engine, actor, catalog, prefix = world
    _, token = await auth.create_api_token(
        db, actor, TokenCreate(name="References", scopes={"global": ["team.read"]})
    )
    _, refused = await auth.create_api_token(
        db, actor, TokenCreate(name="No references", scopes={})
    )

    async def override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = override
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        seen = []
        for offset, count in [(0, 50), (50, 50), (100, 26)]:
            choice = await client.get(
                "/api/v1/teams/directory/options",
                params={"q": prefix, "limit": 50, "offset": offset},
            )
            assert choice.status_code == 200 and choice.headers["X-Total-Count"] == "126", (
                choice.text
            )
            assert len(choice.json()) == count
            params = [("ids", row["value"]) for row in choice.json()]
            sql = []

            def record(conn, cursor, statement, parameters, context, executemany):
                sql.append(statement)

            event.listen(engine.sync_engine, "before_cursor_execute", record)
            try:
                response = await client.get("/api/v1/teams/references", params=params)
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", record)
            assert response.status_code == 200, response.text
            assert len(response.json()) == count
            assert not any("WITH RECURSIVE" in stmt for stmt in sql)
            assert all(
                set(row) == {"id", "name", "member_count"} and row["member_count"] is None
                for row in response.json()
            )
            seen.extend(row["id"] for row in response.json())
            response = await client.get(
                "/api/v1/teams/references", params=[*params, ("include_counts", "true")]
            )
            assert response.status_code == 200, response.text
            assert all(
                row["member_count"] == (0 if row["id"] == str(catalog[-1].id) else 5)
                for row in response.json()
            )
        assert set(seen) == {str(team.id) for team in catalog} and len(seen) == 126
        path = "/api/v1/teams/references"
        params = [("ids", str(team.id)) for team in catalog[:51]]
        assert (await client.get(path, params=params)).status_code == 422
        assert (await client.get(path, params={"ids": "invalid"})).status_code == 422
        assert (await client.get(path)).json() == []
        response = await client.get(
            path,
            params=[
                ("ids", str(catalog[-1].id)),
                ("ids", str(uuid.uuid4())),
                ("ids", str(catalog[-1].id)),
            ],
        )
        assert [row["id"] for row in response.json()] == [str(catalog[-1].id)]
        client.headers["Authorization"] = f"Bearer {refused}"
        response = await client.get(
            path, params={"ids": str(catalog[0].id), "include_counts": "true"}
        )
        assert response.status_code == 200 and response.json() == []
        choice = await client.get("/api/v1/teams/directory/options", params={"q": prefix})
        assert (
            choice.status_code == 200
            and choice.json() == []
            and choice.headers["X-Total-Count"] == "0"
        )


async def test_audience_validation_retains_full_ids_and_preserves_restriction_on_refusal(
    world, monkeypatch
):
    db, engine, actor, catalog, prefix = world
    comment = Comment(
        entity_id=uuid.uuid4(), author_id=actor.id, body="Audience", visibility="internal"
    )
    db.add(comment)
    await db.flush()

    async def forbid_catalog(*args, **kwargs):
        raise AssertionError("Audience writes must not hydrate all teams")

    monkeypatch.setattr(teams, "list_teams", forbid_catalog)
    wanted = [team.id for team in catalog]
    assert await comments._set_teams(db, comment, [*wanted, wanted[0]]) == set(wanted)
    with pytest.raises(ConflictError):
        await comments._set_teams(db, comment, [wanted[0], uuid.uuid4()])
    stored = set(
        await db.scalars(
            select(CommentVisibilityTeam.team_id).where(
                CommentVisibilityTeam.comment_id == comment.id
            )
        )
    )
    assert stored == set(wanted)
    # Public comments ignore even stale audience values; empty internal is unrestricted.
    comment.visibility = "public"
    assert await comments._set_teams(db, comment, [uuid.uuid4()]) == set()
    assert (
        list(
            await db.scalars(
                select(CommentVisibilityTeam.team_id).where(
                    CommentVisibilityTeam.comment_id == comment.id
                )
            )
        )
        == []
    )


async def test_reference_get_remains_available_during_read_only_preview(world):
    from radd.modules.auth.types import SESSION_COOKIE_NAME

    db, engine, actor, catalog, prefix = world
    target = User(
        name="Preview target", email=prefix + "-preview@test.invalid", instance_role="admin"
    )
    db.add(target)
    await db.flush()
    cookie = await auth.create_session(db, actor, method=LoginMethod.PASSWORD)

    async def override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = override
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies={SESSION_COOKIE_NAME: cookie},
    ) as client:
        started = await client.post("/api/v1/auth/view-as", json={"user_id": str(target.id)})
        assert started.status_code == 204, started.text
        response = await client.get(
            "/api/v1/teams/references", params={"ids": str(catalog[0].id), "include_counts": "true"}
        )
        assert response.status_code == 200, response.text
        assert response.json() == [
            {"id": str(catalog[0].id), "name": catalog[0].name, "member_count": 5}
        ]
        refused = await client.patch(
            "/api/v1/teams/" + str(catalog[0].id), json={"name": "Forbidden"}
        )
        assert refused.status_code == 403 and "read-only" in refused.json()["detail"]
        assert (await client.delete("/api/v1/auth/view-as")).status_code == 204
