"""Authorization and lifecycle controls used by the access-management UI."""

from datetime import timedelta

import pytest
from radd.clock import utcnow
from radd.exceptions import ConflictError
from radd.modules.access import service as access
from radd.modules.access.types import GrantSubject
from radd.modules.auth import grants, service as auth
from radd.modules.auth.schemas import GlobalGrantEntry, TokenCreate
from radd.modules.pages import page_access
from test_page_restriction import db as db, _admin, _user, _space, _page, _grant_space_read
from test_authorization_surfaces import client_for, grant, project_item


async def test_restriction_survives_revoke_and_can_be_explicitly_reset(db):
    owner, reader = await _admin(db), await _user(db)
    space = await _space(db, owner)
    page = await _page(db, space, owner)
    await _grant_space_read(db, reader, space)
    row = await access.add_grant(
        db, "page", str(page.id), subject_type=GrantSubject.USER, subject_id=owner.id, access="read"
    )
    await access.remove_grant(db, row.id)
    assert not await page_access.page_access(db, reader, page)
    assert str(page.id) in await access.resource_ids_with_grants(db, "page")
    async with client_for(db, owner) as client:
        modes = await client.get(f"/api/v1/grants/restrictions/page/{page.id}")
        assert modes.status_code == 200
        mode_id = modes.json()[0]["id"]
        assert (await client.delete(f"/api/v1/grants/restrictions/{mode_id}")).status_code == 204
    assert await page_access.page_access(db, reader, page)


async def test_resource_expiry_change_requires_management(db):
    owner, reader = await _admin(db), await _user(db)
    space = await _space(db, owner)
    page = await _page(db, space, owner)
    await _grant_space_read(db, reader, space)
    row = await access.add_grant(
        db,
        "page",
        str(page.id),
        subject_type=GrantSubject.USER,
        subject_id=reader.id,
        access="read",
        expires_at=utcnow() - timedelta(days=1),
    )
    assert not await page_access.page_access(db, reader, page)
    expires = (utcnow() + timedelta(days=1)).isoformat() + "Z"
    async with client_for(db, reader) as client:
        assert (
            await client.patch(f"/api/v1/grants/{row.id}", json={"expires_at": expires})
        ).status_code == 403
    async with client_for(db, owner) as client:
        assert (
            await client.patch(f"/api/v1/grants/{row.id}", json={"expires_at": expires})
        ).status_code == 200
    assert await page_access.page_access(db, reader, page)


async def test_stale_holder_save_cannot_erase_another_administrators_grant(db):
    owner, other = await _admin(db), await _user(db)
    role = await grant(db, owner, "label.create")
    original = await grants.list_grants(db, role.id)
    await grants.create_grant(db, role.id, user_id=other.id)
    with pytest.raises(ConflictError):
        await grants.replace_grants(
            db,
            role.id,
            [GlobalGrantEntry(user_id=owner.id)],
            expected_grant_ids=[g.id for g in original],
        )
    assert len(await grants.list_grants(db, role.id)) == 2


async def test_role_expiry_renewal_preserves_subject_and_scope(db):
    owner, other = await _admin(db), await _user(db)
    project, _ = await project_item(db, owner)
    role = await grant(db, owner, "item.read", project=project)
    row = await grants.create_grant(
        db,
        role.id,
        user_id=other.id,
        project_id=project.id,
        expires_at=utcnow() - timedelta(days=1),
    )
    async with client_for(db, owner) as client:
        response = await client.patch(
            f"/api/v1/role-grants/{row.id}/expiry", json={"expires_at": None}
        )
        assert response.status_code == 200, response.text
        assert response.json()["user_id"] == str(other.id)
        assert response.json()["project_id"] == str(project.id)
        assert response.json()["expires_at"] is None


async def test_space_scoped_reader_gets_wiki_mcp_catalog(db):
    owner, reader = await _admin(db), await _user(db)
    space = await _space(db, owner)
    page = await _page(db, space, owner)
    await _grant_space_read(db, reader, space)
    _, key = await auth.create_api_token(
        db, reader, TokenCreate(name="Wiki reader", scopes={"global": ["page.read"]})
    )
    async with client_for(db, key=key) as client:
        response = await client.post(
            "/api/v1/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        names = {t["name"] for t in response.json()["result"]["tools"]}
        assert {"get_page", "search_pages"} <= names
        response = await client.post(
            "/api/v1/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_page", "arguments": {"id": str(page.id)}},
            },
        )
        assert not response.json()["result"]["isError"]


async def test_delegated_role_picker_only_offers_covered_roles(db):
    owner, delegate = await _admin(db), await _user(db)
    project, _ = await project_item(db, owner)
    await grant(db, delegate, "role.read")
    await grant(db, delegate, "item.read", "member.create", project=project)
    safe = await grant(db, owner, "item.read", project=project)
    powerful = await grant(db, owner, "item.delete", project=project)
    async with client_for(db, delegate) as client:
        response = await client.get(
            "/api/v1/roles/assignable/options", params={"project_id": str(project.id), "limit": 200}
        )
        assert response.status_code == 200, response.text
        ids = {row["value"] for row in response.json()}
        assert str(safe.id) in ids
        assert str(powerful.id) not in ids


async def test_team_steward_sees_access_counts_without_resource_titles(db):
    from radd.modules.teams import service as teams
    from radd.modules.teams.schemas import TeamCreate

    owner = await _admin(db)
    team = await teams.create_team(db, TeamCreate(name="Impact review"), actor_id=owner.id)
    role = await grant(db, owner, "item.read")
    await grants.create_grant(db, role.id, team_id=team.id)
    await access.add_grant(
        db,
        "builtin_field",
        "description",
        subject_type=GrantSubject.TEAM,
        subject_id=team.id,
        access="read",
    )
    async with client_for(db, owner) as client:
        response = await client.get(f"/api/v1/teams/{team.id}/access-impact")
        assert response.status_code == 200, response.text
        assert response.json()["roles"] == response.json()["global_roles"] == 1
        assert response.json()["resource_rules"] == [{"label": "Builtin field", "count": 1}]


async def test_notification_with_missing_source_event_is_not_delivered(db):
    from radd.modules.notify.authorization import notification_readable
    from radd.modules.notify.models import Notification

    owner = await _admin(db)
    _, item = await project_item(db, owner)
    row = Notification(
        user_id=owner.id,
        item_id=item.id,
        type="mentioned",
        event_id=999999999,
        payload={"excerpt": "Unverifiable discussion"},
    )
    assert not await notification_readable(db, row, owner)
