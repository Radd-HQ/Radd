"""Cross-surface authorization regressions (RADD-1213)."""

from test_page_restriction import db as db


import io
import uuid
import zipfile
from contextlib import asynccontextmanager
import httpx
import pytest
from radd.app import create_app
from radd.db import get_session
from radd.modules.auth import authz, service as auth, grants, roles
from radd.modules.auth.schemas import TokenCreate, RoleCreate
from radd.modules.auth.types import Permission, SESSION_COOKIE_NAME
from radd.modules.pages import service as pages, page_access
from radd.modules.pages.schemas import PageCreate
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.items.enums import ItemVisibility
from test_page_restriction import _admin, _user, _space, _page, _grant_space_read, _restrict


@asynccontextmanager
async def client_for(db, user=None, key=None):
    app = create_app()

    async def override():
        yield db

    app.dependency_overrides[get_session] = override
    cookies = {SESSION_COOKIE_NAME: await auth.create_session(db, user)} if user else {}
    headers = {"Authorization": "Bearer " + key} if key else {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies=cookies,
        headers=headers,
    ) as c:
        yield c


async def grant(db, user, *atoms, project=None):
    role = await roles.create_role(
        db, RoleCreate(key="aud" + uuid.uuid4().hex[:8], name="Audit", permissions=list(atoms))
    )
    await grants.create_grant(
        db, role.id, user_id=user.id, project_id=project.id if project else None
    )
    return role


async def project_item(db, owner, visibility=ItemVisibility.INTERNAL):
    project = await projects.create_project(
        db, ProjectCreate(key="AU" + uuid.uuid4().hex[:6], name="Audit project")
    )
    item = await items.create_item(
        db,
        ItemCreate(project_id=project.id, title="Audit secret issue", visibility=visibility),
        actor=owner,
    )
    return project, item


async def test_mcp_refuses_wiki_reads_with_zero_scope_key(db):
    owner = await _admin(db)
    space = await _space(db, owner)
    page = await _page(db, space, owner, "Auditsecretalpha")
    await _restrict(db, page, owner, user_id=owner.id)
    _, key = await auth.create_api_token(
        db, owner, TokenCreate(name="No rights", scopes={"global": []})
    )
    async with client_for(db, key=key) as c:
        normal = await c.get(f"/api/v1/pages/{page.id}")
        assert normal.status_code in (403, 404)
        listed = await c.post(
            "/api/v1/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        assert "get_page" not in [t["name"] for t in listed.json()["result"]["tools"]]
        for name, args in [
            ("search_pages", {"query": "Auditsecretalpha"}),
            ("get_page", {"id": str(page.id)}),
        ]:
            r = await c.post(
                "/api/v1/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": args},
                },
            )
            assert r.status_code == 200, r.text
            assert "Auditsecretalpha" not in r.text, r.text


async def test_events_refuse_non_admin_readers(db):
    owner = await _admin(db)
    reader = await _user(db)
    project, item = await project_item(db, owner, ItemVisibility.RESTRICTED)
    await grant(db, reader, "item.read@own", project=project)
    async with client_for(db, reader) as c:
        assert (await c.get(f"/api/v1/items/{item.id}")).status_code in (403, 404)
        r = await c.get("/api/v1/events?limit=500")
        assert r.status_code == 403, r.text


async def test_export_excludes_restricted_descendants(db):
    owner = await _admin(db)
    reader = await _user(db)
    space = await _space(db, owner)
    root = await _page(db, space, owner, "Public parent")
    child = await pages.create_page(
        db,
        PageCreate(
            space_id=space.id,
            parent_id=root.id,
            title="Secret child",
            body="CONFIDENTIAL EXPORT BYTES",
        ),
        owner.id,
    )
    await _grant_space_read(db, reader, space)
    await _restrict(db, child, owner, user_id=owner.id)
    async with client_for(db, reader) as c:
        assert (await c.get(f"/api/v1/pages/{child.id}")).status_code == 404
        r = await c.get(f"/api/v1/pages/{root.id}/export")
        assert r.status_code == 200, r.text
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            assert not any(b"CONFIDENTIAL EXPORT BYTES" in z.read(n) for n in z.namelist())


async def test_backlinks_hide_private_space_title(db):
    owner = await _admin(db)
    reader = await _user(db)
    public = await _space(db, owner, "Readable")
    private = await _space(db, owner, "Secret")
    target = await _page(db, public, owner, "Allowed")
    source = await pages.create_page(
        db,
        PageCreate(
            space_id=private.id,
            title="Secret acquisition target",
            body=f"[link](/pages/{target.id})",
        ),
        owner.id,
    )
    await _grant_space_read(db, reader, public)
    async with client_for(db, reader) as c:
        assert (await c.get(f"/api/v1/pages/{source.id}")).status_code in (403, 404)
        r = await c.get(f"/api/v1/pages/{target.id}/backlinks")
        assert r.status_code == 200, r.text
        assert not any(p["title"] == source.title for p in r.json())


async def test_item_docs_hide_private_space_title(db):
    from radd.modules.pages.models import ItemPageLink

    owner = await _admin(db)
    reader = await _user(db)
    space = await _space(db, owner)
    page = await _page(db, space, owner)
    project, item = await project_item(db, owner)
    await grant(db, reader, "item.read", project=project)
    db.add(ItemPageLink(item_id=item.id, page_id=page.id, created_by=owner.id))
    await db.flush()
    async with client_for(db, reader) as c:
        assert (await c.get(f"/api/v1/pages/{page.id}")).status_code in (403, 404)
        r = await c.get(f"/api/v1/items/{item.id}/pages")
        assert r.status_code == 200, r.text
        assert not any(p["title"] == page.title for p in r.json())


async def test_page_item_links_enforce_item_row_guard(db):
    from radd.modules.pages.models import ItemPageLink

    owner = await _admin(db)
    reader = await _user(db)
    space = await _space(db, owner)
    page = await _page(db, space, owner)
    project, item = await project_item(db, owner, ItemVisibility.RESTRICTED)
    await grant(db, reader, "item.read", project=project)
    await _grant_space_read(db, reader, space, Permission.PAGE_WRITE)
    async with client_for(db, reader) as c:
        assert (await c.get(f"/api/v1/items/{item.id}")).status_code in (403, 404)
        r = await c.post(f"/api/v1/pages/{page.id}/items", json={"item_key": item.key})
        assert r.status_code in (403, 404), r.text
        db.add(ItemPageLink(item_id=item.id, page_id=page.id, created_by=owner.id))
        await db.flush()
        r = await c.get(f"/api/v1/pages/{page.id}/items")
        assert not any(i["item_id"] == str(item.id) for i in r.json()), r.text


async def test_wiki_create_under_restricted_parent_is_refused(db):
    owner = await _admin(db)
    reader = await _user(db)
    space = await _space(db, owner)
    parent = await _page(db, space, owner)
    await _grant_space_read(db, reader, space, Permission.PAGE_WRITE)
    await _restrict(db, parent, owner, user_id=owner.id)
    async with client_for(db, reader) as c:
        assert (await c.get(f"/api/v1/pages/{parent.id}")).status_code == 404
        r = await c.post(
            "/api/v1/pages",
            json={
                "space_id": str(space.id),
                "parent_id": str(parent.id),
                "title": "Injected child",
            },
        )
        assert r.status_code in (403, 404), r.text


async def test_team_owner_zero_scope_key_cannot_grant_membership(db):
    from radd.modules.teams import service as teams
    from radd.modules.teams.schemas import TeamCreate

    owner = await _admin(db)
    other = await _user(db)
    team = await teams.create_team(db, TeamCreate(name="Privileged team"), actor_id=owner.id)
    role = await roles.create_role(
        db, RoleCreate(key="aud" + uuid.uuid4().hex[:8], name="Power", permissions=["role.update"])
    )
    await grants.create_grant(db, role.id, team_id=team.id)
    _, key = await auth.create_api_token(
        db, owner, TokenCreate(name="No rights", scopes={"global": []})
    )
    assert "role.update" not in await authz.effective_permissions(db, other)
    async with client_for(db, key=key) as c:
        r = await c.post(f"/api/v1/teams/{team.id}/members", json={"user_id": str(other.id)})
        assert r.status_code == 403, r.text
    assert "role.update" not in await authz.effective_permissions(db, other)


async def test_deflection_hides_restricted_page(db, monkeypatch):
    from radd.modules.search import deflect

    async def no_semantic(*args, **kwargs):
        return []

    monkeypatch.setattr(deflect, "_semantic_doc_ids", no_semantic)
    owner = await _admin(db)
    reader = await _user(db)
    space = await _space(db, owner)
    page = await _page(db, space, owner, "Auditsecretdeflect")
    await _grant_space_read(db, reader, space)
    await _restrict(db, page, owner, user_id=owner.id)
    project, _ = await project_item(db, owner)
    await grant(db, reader, "item.read", project=project)
    async with client_for(db, reader) as c:
        assert (await c.get(f"/api/v1/pages/{page.id}")).status_code == 404
        r = await c.get(
            "/api/v1/search/deflect",
            params={"project_id": str(project.id), "q": "Auditsecretdeflect"},
        )
        assert r.status_code == 200, r.text
        assert not any(p["id"] == str(page.id) for p in r.json()["docs"])


async def test_semantic_materialization_enforces_page_restriction_and_space(db, monkeypatch):
    from radd.modules.search import semantic, deflect

    owner = await _admin(db)
    reader = await _user(db)
    space = await _space(db, owner)
    page = await _page(db, space, owner)
    await _grant_space_read(db, reader, space)
    await _restrict(db, page, owner, user_id=owner.id)

    class FakeCandidates:
        async def doc_candidates(self, *args, **kwargs):
            return [(page.id, 0.1)]

    assert not await page_access.page_access(db, reader, page)
    hits = await semantic._docs(db, reader, "query", FakeCandidates())
    assert not hits

    async def candidate_ids(*args, **kwargs):
        return [page.id]

    monkeypatch.setattr(deflect, "_semantic_doc_ids", candidate_ids)
    hits = await deflect.deflect_docs(db, "unmatchedxyz", space_ids=set())
    assert not hits


async def test_mcp_log_work_refuses_read_only_key(db):
    from radd.modules.timelogging import enablement

    owner = await _admin(db)
    project, item = await project_item(db, owner)
    await enablement.set_enabled(db, project.id, True)
    _, key = await auth.create_api_token(
        db, owner, TokenCreate(name="Read only", scopes={"global": ["item.read"]})
    )
    async with client_for(db, key=key) as c:
        r = await c.post(f"/api/v1/items/{item.id}/worklogs", json={"time_spent": "1h"})
        assert r.status_code == 403, r.text
        r = await c.post(
            "/api/v1/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "log_work", "arguments": {"key": item.key, "time_spent": "1h"}},
            },
        )
        assert r.status_code == 200 and r.json()["result"]["isError"], r.text


async def test_estimate_write_enforces_own_relation(db):
    from radd.modules.timelogging import enablement

    owner = await _admin(db)
    reader = await _user(db)
    project, item = await project_item(db, owner)
    await enablement.set_enabled(db, project.id, True)
    await grant(db, reader, "item.read", "item.update@own", project=project)
    async with client_for(db, reader) as c:
        r = await c.patch(f"/api/v1/items/{item.id}", json={"title": "Forbidden change"})
        assert r.status_code == 403, r.text
        r = await c.put(f"/api/v1/items/{item.id}/estimate", json={"estimate": "8h"})
        assert r.status_code == 403, r.text


@pytest.mark.parametrize("channel", ["immediate", "digest"])
async def test_queued_notification_is_dropped_after_access_revocation(db, monkeypatch, channel):
    from radd.modules.notify import mailer, emailer
    from radd.modules.notify.models import Notification

    owner = await _admin(db)
    reader = await _user(db)
    project, item = await project_item(db, owner)
    role = await grant(db, reader, "item.read", project=project)
    await items.require_readable_item(db, item.id, reader)
    row = Notification(
        user_id=reader.id,
        type="assigned",
        item_id=item.id,
        actor_id=owner.id,
        payload={"item_key": item.key, "item_title": "Private after revocation"},
        email=channel == "immediate",
        inbox=True,
    )
    db.add(row)
    await db.flush()
    from sqlalchemy import delete
    from radd.modules.auth.models import GlobalRoleGrant

    await db.execute(delete(GlobalRoleGrant).where(GlobalRoleGrant.role_id == role.id))
    await db.flush()
    async with client_for(db, reader) as c:
        assert (await c.get(f"/api/v1/items/{item.id}")).status_code in (403, 404)
    captured = []

    async def can_send(*args, **kwargs):
        return True

    async def capture(*args, **kwargs):
        captured.append((args, kwargs))
        return True

    monkeypatch.setattr(mailer, "can_send", can_send)
    if channel == "immediate":
        monkeypatch.setattr(mailer, "_mail_transport", lambda: None)
        monkeypatch.setattr(mailer, "_send_direct", capture)
        sent = await mailer.run_batch(db)
    else:
        monkeypatch.setattr(mailer, "send_plain", capture)
        sent = await emailer.run_batch(db)
    assert sent == 0 and not captured
    assert row.emailed_at is not None


@pytest.mark.parametrize("key_scope", [{"global": []}, {"global": ["item.update@own"]}])
async def test_zero_scope_key_cannot_decline_approval(db, key_scope):
    from radd.modules.approvals.models import ApprovalRequest

    owner = await _admin(db)
    reader = await _user(db)
    project, item = await project_item(db, owner)
    request = ApprovalRequest(
        item_id=item.id,
        to_state_id=item.state.id,
        requested_by=owner.id,
        status="pending",
        approvers=[{"kind": "user", "id": str(reader.id), "name": reader.name}],
    )
    db.add(request)
    await db.flush()
    _, key = await auth.create_api_token(
        db, reader, TokenCreate(name="No rights", scopes=key_scope)
    )
    async with client_for(db, key=key) as c:
        r = await c.post(f"/api/v1/approvals/{request.id}/vote", json={"verdict": "decline"})
        assert r.status_code == 403, r.text
        assert request.status == "pending"
