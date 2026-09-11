"""Portal share windows must preserve scoped policy and independent writes."""

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.exceptions import NotFoundError
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.forms import portal, service, sharing
from radd.modules.forms.models import FormShare
from radd.modules.forms.schemas import FormCreate, FormShareEntry, FormSharingUpdate
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams.models import Team


@pytest.fixture
async def world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        prefix = uuid.uuid4().hex
        actor = User(name="Portal manager", email=prefix + "@test.invalid", instance_role="admin")
        people = [
            User(name=f"{prefix} Person {i:03}", email=f"{prefix}-{i}@test.invalid")
            for i in range(252)
        ]
        teams = [Team(name=f"{prefix} Team {i:03}") for i in range(252)]
        db.add_all([actor, *people, *teams])
        await db.flush()
        project = await projects.create_project(
            db, ProjectCreate(key="FS" + prefix[:6], name="Portal"), actor_id=actor.id
        )
        form = await service.create_form(
            db, FormCreate(project_id=project.id, name="Shared form"), actor
        )
        saved = [FormShare(form_id=form.id, user_id=user.id) for user in people[:126]]
        saved += [FormShare(form_id=form.id, team_id=team.id) for team in teams[:126]]
        db.add_all(saved)
        people[125].active = False
        await db.flush()
        yield db, engine, actor, project, form, people, teams, saved, prefix
        await db.rollback()
    await engine.dispose()


async def test_share_windows_candidate_exclusion_and_scoped_name_policy(world):
    db, engine, actor, project, form, people, teams, saved, prefix = world
    scopes = {"projects": {str(project.id): ["form.manage"]}, "global": ["team.read"]}
    _, token = await auth.create_api_token(
        db, actor, TokenCreate(name="Scoped manager", scopes=scopes)
    )
    _, no_names = await auth.create_api_token(
        db,
        actor,
        TokenCreate(name="No team names", scopes={"projects": {str(project.id): ["form.manage"]}}),
    )
    _, denied = await auth.create_api_token(
        db,
        actor,
        TokenCreate(
            name="Read only",
            scopes={"projects": {str(project.id): ["item.read"]}, "global": ["team.read"]},
        ),
    )

    async def override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = override
    path = f"/api/v1/forms/{form.id}/sharing"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        seen = []
        for offset in range(0, 252, 50):
            response = await client.get(path, params={"limit": 50, "offset": offset})
            assert response.status_code == 200, response.text
            assert response.headers["X-Total-Count"] == "252" and len(response.json()) <= 50
            seen.extend(response.json())
        assert {row["id"] for row in seen} == {str(row.id) for row in saved}
        assert all(row["subject_name"] for row in seen)
        assert next(row for row in seen if row["user_id"] == str(people[125].id))["active"] is False
        for kind, expected in [("user", people[126:]), ("team", teams[126:])]:
            found = []
            for offset, count in [(0, 50), (50, 50), (100, 26)]:
                response = await client.get(
                    path + "/candidates",
                    params={"kind": kind, "q": prefix, "limit": 50, "offset": offset},
                )
                assert response.status_code == 200, response.text
                assert response.headers["X-Total-Count"] == "126" and len(response.json()) == count
                found.extend(row["value"] for row in response.json())
            assert set(found) == {str(row.id) for row in expected}
        client.headers["Authorization"] = f"Bearer {no_names}"
        response = await client.get(path, params={"q": prefix + " Team"})
        assert (
            response.status_code == 200
            and response.json() == []
            and response.headers["X-Total-Count"] == "0"
        )
        response = await client.get(path + "/candidates", params={"kind": "team", "q": prefix})
        assert response.json() == [] and response.headers["X-Total-Count"] == "0"
        response = await client.get(path, params={"offset": 150})
        team_rows = [row for row in response.json() if row["team_id"]]
        assert team_rows and all(row["subject_name"] is None for row in team_rows)
        client.headers["Authorization"] = f"Bearer {denied}"
        for suffix in ("", "/candidates?kind=user"):
            assert (await client.get(path + suffix)).status_code == 403
        assert (await client.post(path, json={"user_id": str(people[126].id)})).status_code == 403
        assert (await client.delete(path + "/" + str(saved[0].id))).status_code == 403
        client.headers["Authorization"] = f"Bearer {token}"
        for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}, {"q": "x" * 201}):
            assert (await client.get(path, params=params)).status_code == 422
        assert (await client.get(path + "/candidates", params={"kind": "group"})).status_code == 422
        assert (await client.get(path, params={"q": "%_"})).json() == []


async def test_individual_mutations_preserve_unseen_inactive_shares_and_portal_rights(world):
    db, engine, actor, project, form, people, teams, saved, prefix = world

    async def override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = override
    _, token = await auth.create_api_token(db, actor, TokenCreate(name="Sharing"))
    path = f"/api/v1/forms/{form.id}/sharing"
    user = people[-1]
    with pytest.raises(NotFoundError):
        await portal._eligible_form(db, form.id, user)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.post(path, json={"user_id": str(user.id)})
        assert response.status_code == 201, response.text
        added = response.json()
        assert set(added) == {"id", "user_id", "team_id", "created_at"}
        assert (await portal._eligible_form(db, form.id, user)).id == form.id
        assert (await client.post(path, json={"user_id": str(user.id)})).status_code == 409
        assert (await client.post(path, json={"user_id": str(people[125].id)})).status_code == 409
        assert set(await db.scalars(select(FormShare.id).where(FormShare.form_id == form.id))) == {
            row.id for row in saved
        } | {uuid.UUID(added["id"])}
        assert (await client.delete(path + "/" + added["id"])).status_code == 204
        with pytest.raises(NotFoundError):
            await portal._eligible_form(db, form.id, user)
        other = await service.create_form(
            db, FormCreate(project_id=project.id, name="Other"), actor
        )
        foreign = await sharing.add(db, other.id, FormShareEntry(team_id=teams[-1].id), actor)
        assert (await client.delete(path + "/" + str(foreign.id))).status_code == 404
        assert await db.get(FormShare, foreign.id) is not None
        assert set(await db.scalars(select(FormShare.id).where(FormShare.form_id == form.id))) == {
            row.id for row in saved
        }
        # Removing an inactive recipient does not require revalidating the others.
        inactive = next(row for row in saved if row.user_id == people[125].id)
        assert (await client.delete(path + "/" + str(inactive.id))).status_code == 204
        legacy = await client.put(path, json={"shares": [{"user_id": str(user.id)}]})
        assert legacy.status_code == 200 and len(legacy.json()["shares"]) == 1
        assert legacy.json()["shares"][0]["user_id"] == str(user.id)


async def test_management_reads_can_omit_all_share_hydration_without_changing_legacy(world):
    db, engine, actor, project, form, *_ = world
    sql = []

    def record(conn, cursor, statement, parameters, context, executemany):
        sql.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        rows = await service.list_forms(db, project.id, actor, include_shares=False)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    assert len(rows) == 1 and rows[0].shares == []
    assert not any("form_shares" in statement for statement in sql)
    legacy = await service.list_forms(db, project.id, actor)
    assert len(legacy[0].shares) == 252


@pytest.mark.parametrize("first_kind", ["add", "replace"])
async def test_concurrent_additions_serialize_without_replacing_either_recipient(first_kind):
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as setup:
        prefix = uuid.uuid4().hex
        actor = User(name="Concurrent owner", email=prefix + "@test.invalid", instance_role="admin")
        teams = [Team(name=prefix + str(i)) for i in range(2)]
        setup.add_all([actor, *teams])
        await setup.flush()
        project = await projects.create_project(
            setup, ProjectCreate(key="FC" + prefix[:6], name="Concurrent"), actor_id=actor.id
        )
        form = await service.create_form(
            setup, FormCreate(project_id=project.id, name="Concurrent"), actor
        )
        await setup.commit()
    async with maker() as first, maker() as second:
        first_actor = await first.get(User, actor.id)
        second_actor = await second.get(User, actor.id)
        if first_kind == "add":
            await sharing.add(first, form.id, FormShareEntry(team_id=teams[0].id), first_actor)
        else:
            await service.update_sharing(
                first,
                form.id,
                FormSharingUpdate(shares=[FormShareEntry(team_id=teams[0].id)]),
                first_actor,
            )
        waiting = asyncio.create_task(
            sharing.add(second, form.id, FormShareEntry(team_id=teams[1].id), second_actor)
        )
        await asyncio.sleep(0.05)
        assert not waiting.done(), "second writer must wait for the form row lock"
        await first.commit()
        await asyncio.wait_for(waiting, 5)
        await second.commit()
    async with maker() as check:
        assert set(
            await check.scalars(select(FormShare.team_id).where(FormShare.form_id == form.id))
        ) == {row.id for row in teams}
    await engine.dispose()
