"""Grant lifecycle and attachment authorization regressions (RADD-1213)."""

from test_view_sharing import db as db
from test_attachment_acl import setup as setup


import uuid
from datetime import timedelta
import httpx
from radd.app import create_app
from radd.db import get_session
from radd.clock import utcnow
from radd.modules.access import service as access, inspect
from radd.modules.access.types import GrantSubject
from radd.modules.attachments import acl
from radd.modules.auth import service as auth, grants, authz
from radd.modules.auth.schemas import TokenCreate, GlobalGrantEntry, GlobalGrantsUpdate
from radd.modules.auth.principals import SIGNED_IN_ID, ensure_principals
from radd.modules.auth.types import InstanceRole
from radd.modules.views import service as views
from radd.modules.views.schemas import ViewCreate
from radd.modules.views.types import ViewType
from test_view_sharing import _member
from test_global_grants import _role
from radd.modules.auth.types import LoginMethod


async def test_expiring_last_allow_keeps_attachment_restricted(db, setup):
    owner, reader, item, attachment = setup
    grant = await access.add_grant(
        db,
        "attachment",
        str(attachment.id),
        subject_type=GrantSubject.USER,
        subject_id=owner.id,
        access="read",
        expires_at=utcnow() + timedelta(days=1),
    )
    assert not await acl.attachment_readable(db, reader, attachment)
    grant.expires_at = utcnow() - timedelta(seconds=1)
    await db.flush()
    assert not await acl.attachment_readable(db, reader, attachment)


async def test_read_only_owner_key_cannot_regrant_private_view(db):
    owner = await _member(db, "Owner", instance_role=InstanceRole.ADMIN)
    other = await _member(db, "Other")
    view = await views.create_view(
        db, ViewCreate(name="Private audit board", view_type=ViewType.BOARD), actor=owner
    )
    _, key = await auth.create_api_token(
        db, owner, TokenCreate(name="Read only", scopes={"global": ["item.read"]})
    )
    app = create_app()

    async def override():
        yield db

    app.dependency_overrides[get_session] = override
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer " + key},
    ) as client:
        r = await client.post(
            "/api/v1/grants",
            json={
                "resource_type": "view",
                "resource_id": str(view.id),
                "subject_type": "user",
                "subject_id": str(other.id),
                "access": "owner",
            },
        )
        assert r.status_code == 403, r.text
        assert "view.update" not in await authz.effective_permissions(db, owner)


async def test_global_editor_preserves_temporary_grant(db):
    person = await _member(db, "Temporary")
    role = await _role(db, "label.create")
    row = await grants.create_grant(
        db, role.id, user_id=person.id, expires_at=utcnow() + timedelta(hours=1)
    )
    assert row.expires_at is not None
    saved = await grants.replace_grants(db, role.id, [GlobalGrantEntry(user_id=person.id)])
    assert len(saved) == 1 and saved[0].expires_at == row.expires_at
    assert saved[0].id == row.id


def test_global_editor_accepts_group_subject():
    gid = uuid.uuid4()
    result = GlobalGrantsUpdate.model_validate(
        {"expected_grant_ids": [], "grants": [{"group_id": str(gid)}]}
    )
    assert result.grants[0].group_id == gid


async def test_resource_inspector_includes_signed_in_principal(db):
    await ensure_principals(db)
    person = await _member(db, "Inspect me")
    rid = str(uuid.uuid4())
    await access.add_grant(
        db,
        "attachment",
        rid,
        subject_type=GrantSubject.USER,
        subject_id=SIGNED_IN_ID,
        access="read",
    )
    result = await inspect.subject_access(db, user_id=person.id)
    assert any(row.resource_id == rid for section in result for row in section.rows)


async def test_wiki_attachment_role_deny_is_enforced(db, setup):
    import io
    from fastapi import UploadFile
    from radd.modules.attachments import service as files
    from radd.modules.access.types import GrantEffect
    from test_page_restriction import _space, _page

    owner, reader, _, _ = setup
    space = await _space(db, owner, "Wiki")
    page = await _page(db, space, owner)
    role = await _role(db, "page.read")
    await grants.create_grant(db, role.id, user_id=reader.id, space_id=space.id)
    attachment = await files.save_upload(
        db,
        entity_type="page",
        entity_id=page.id,
        upload=UploadFile(file=io.BytesIO(b"private"), filename="wiki.txt"),
        actor_id=owner.id,
    )
    await access.add_grant(
        db,
        "attachment",
        str(attachment.id),
        subject_type=GrantSubject.ROLE,
        subject_id=role.id,
        access="read",
        effect=GrantEffect.DENY,
    )
    assert not await acl.attachment_readable(db, reader, attachment)


async def test_restricted_wiki_page_hides_attachments(db, setup, monkeypatch):
    import io
    from fastapi import UploadFile
    from radd.modules.attachments import service as files
    from radd.modules.pages import page_access
    from test_page_restriction import _space, _page, _restrict

    owner, reader, _, _ = setup
    space = await _space(db, owner, "Restricted")
    page = await _page(db, space, owner)
    role = await _role(db, "page.read")
    await grants.create_grant(db, role.id, user_id=reader.id, space_id=space.id)
    attachment = await files.save_upload(
        db,
        entity_type="page",
        entity_id=page.id,
        upload=UploadFile(file=io.BytesIO(b"sensitive bytes"), filename="secret.txt"),
        actor_id=owner.id,
    )
    await _restrict(db, page, owner, user_id=owner.id)
    assert not await page_access.page_access(db, reader, page)
    assert not await acl.attachment_readable(db, reader, attachment)
    from importlib import import_module

    attachment_router = import_module("radd.modules.attachments.router")

    async def no_commit(session):
        pass

    monkeypatch.setattr(attachment_router, "commit_before_streaming", no_commit)
    app = create_app()

    async def override():
        yield db

    app.dependency_overrides[get_session] = override
    cookie = await auth.create_session(db, reader, method=LoginMethod.PASSWORD)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies={"radd_session": cookie},
    ) as client:
        p = await client.get(f"/api/v1/pages/{page.id}")
        assert p.status_code in (403, 404), p.text
        listing = await client.get(
            "/api/v1/attachments", params={"entity_type": "page", "entity_id": str(page.id)}
        )
        assert listing.status_code in (403, 404), listing.text
        download = await client.get(f"/api/v1/attachments/{attachment.id}")
        assert download.status_code in (403, 404)
