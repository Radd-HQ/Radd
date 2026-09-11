"""Space directory policy must match direct reads for the authenticated principal."""

import uuid
from datetime import timedelta
import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from radd.app import create_app
from radd.clock import utcnow
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import authz, roles, service as auth
from radd.modules.auth.models import User, Role, GlobalRoleGrant
from radd.modules.auth.scopes import TokenScope
from radd.modules.auth.schemas import TokenCreate
from radd.modules.auth.types import BuiltinRoleKey, Permission, UserSource
from radd.modules.pages import access
from radd.modules.pages.models import PageSpace, PageTemplate


@pytest.mark.parametrize(
    "kind,scope",
    [
        ("member", "empty"),
        ("member", "read"),
        ("member", "project"),
        ("admin", "empty"),
        ("admin", "read"),
        ("admin", "none"),
        ("requester", "none"),
        ("requester", "read"),
        ("service", "read"),
        ("inactive", "none"),
    ],
)
async def test_space_batch_equals_direct_effective_permissions(kind, scope):
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        prefix = uuid.uuid4().hex
        baseline = await roles.role_by_key(db, BuiltinRoleKey.BASELINE)
        baseline.permissions = ["page.read", "page.write"]
        requester = await roles.role_by_key(db, BuiltinRoleKey.REQUESTER)
        requester.permissions = []
        actor = User(
            name="Space principal",
            email=prefix + "@test.invalid",
            instance_role="admin" if kind == "admin" else "member",
            active=kind != "inactive",
            source=UserSource.EMAIL
            if kind == "requester"
            else UserSource.SERVICE
            if kind == "service"
            else UserSource.LOCAL,
        )
        spaces = [PageSpace(name=f"{prefix} {i}", slug=f"{prefix}-{i}") for i in range(2)]
        common = Role(key=prefix + "-common", name="Common", permissions=["comment.write"])
        scoped = Role(key=prefix + "-scoped", name="Scoped", permissions=["page.manage"])
        expired = Role(key=prefix + "-expired", name="Expired", permissions=["role.manage"])
        db.add_all([actor, *spaces, common, scoped, expired])
        await db.flush()
        db.add(GlobalRoleGrant(user_id=actor.id, role_id=common.id))
        db.add(GlobalRoleGrant(user_id=actor.id, role_id=scoped.id, space_id=spaces[0].id))
        db.add(
            GlobalRoleGrant(
                user_id=actor.id,
                role_id=expired.id,
                space_id=spaces[1].id,
                expires_at=utcnow() - timedelta(days=1),
            )
        )
        await db.flush()
        db.info.clear()
        actor.token_scope = (
            None
            if scope == "none"
            else TokenScope(
                global_atoms=frozenset({Permission.PAGE_READ}) if scope == "read" else frozenset(),
                project_atoms={
                    uuid.uuid4(): frozenset({Permission.PAGE_READ, Permission.PAGE_WRITE})
                }
                if scope == "project"
                else {},
            )
        )
        expected = {
            space.id: await authz.effective_permissions(db, actor, space_id=space.id)
            for space in spaces
        }
        actual = await access.permissions_by_space(db, actor, [space.id for space in spaces])
        assert actual == expected
        assert set(await access.readable_spaces(db, actor)) & set(expected) == {
            key for key, value in expected.items() if Permission.PAGE_READ in value
        }
        assert await access.permissions_by_space(db, actor, []) == {}
        await db.rollback()
    await engine.dispose()


@pytest.mark.parametrize("kind", ["restricted-key", "requester", "limited-reader"])
async def test_space_catalog_and_unscoped_templates_do_not_expose_unreadable_content(kind):
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        prefix = uuid.uuid4().hex
        baseline = await roles.role_by_key(db, BuiltinRoleKey.BASELINE)
        baseline.permissions = ["page.read", "page.write"] if kind != "limited-reader" else []
        requester = await roles.role_by_key(db, BuiltinRoleKey.REQUESTER)
        requester.permissions = []
        actor = User(
            name="Wiki principal",
            email=prefix + "@test.invalid",
            source=UserSource.EMAIL if kind == "requester" else UserSource.LOCAL,
        )
        spaces = [PageSpace(name=f"{prefix} {i}", slug=f"{prefix}-{i}") for i in range(2)]
        db.add_all([actor, *spaces])
        await db.flush()
        templates = [
            PageTemplate(name=prefix + " global", body="Global fixture", created_by=actor.id),
            PageTemplate(
                name=prefix + " permitted",
                body="Permitted fixture",
                space_id=spaces[0].id,
                created_by=actor.id,
            ),
            PageTemplate(
                name=prefix + " hidden",
                body="Hidden fixture",
                space_id=spaces[1].id,
                created_by=actor.id,
            ),
        ]
        db.add_all(templates)
        if kind == "limited-reader":
            role = Role(key=prefix, name=prefix, permissions=["page.read"])
            db.add(role)
            await db.flush()
            db.add(GlobalRoleGrant(user_id=actor.id, role_id=role.id, space_id=spaces[0].id))
        await db.flush()
        db.info.clear()
        _, token = await auth.create_api_token(
            db, actor, TokenCreate(name="Wiki", scopes={} if kind == "restricted-key" else None)
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
            r = await client.get("/api/v1/page-spaces")
            assert r.status_code == 200, r.text
            assert {space["id"] for space in r.json()} == (
                {str(spaces[0].id)} if kind == "limited-reader" else set()
            )
            r = await client.get("/api/v1/page-templates")
            assert r.status_code == 200, r.text
            assert {t["id"] for t in r.json()} & {str(t.id) for t in templates} == (
                {str(t.id) for t in templates[:2]} if kind == "limited-reader" else set()
            )
            assert all(t["space_id"] in (None, str(spaces[0].id)) for t in r.json())
            if kind != "limited-reader":
                assert r.json() == []
            r = await client.get("/api/v1/page-templates", params={"space_id": str(spaces[1].id)})
            assert r.status_code == 403
        await db.rollback()
    await engine.dispose()


async def test_template_application_cannot_cross_space_scope():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        prefix = uuid.uuid4().hex
        baseline = await roles.role_by_key(db, BuiltinRoleKey.BASELINE)
        baseline.permissions = []
        actor = User(name="Template writer", email=prefix + "@test.invalid")
        spaces = [PageSpace(name=prefix + str(i), slug=prefix + str(i)) for i in range(2)]
        role = Role(key=prefix, name=prefix, permissions=["page.read", "page.write"])
        db.add_all([actor, *spaces, role])
        await db.flush()
        db.add(GlobalRoleGrant(user_id=actor.id, role_id=role.id, space_id=spaces[0].id))
        templates = [
            PageTemplate(
                name=prefix + " hidden",
                space_id=spaces[1].id,
                body="Hidden template body",
                created_by=actor.id,
            ),
            PageTemplate(
                name=prefix + " local",
                space_id=spaces[0].id,
                body="Local {{title}}",
                created_by=actor.id,
            ),
            PageTemplate(name=prefix + " global", body="Global {{author}}", created_by=actor.id),
        ]
        db.add_all(templates)
        await db.flush()
        db.info.clear()
        _, token = await auth.create_api_token(
            db, actor, TokenCreate(name="Writer", scopes={"global": ["page.read", "page.write"]})
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
            r = await client.post(
                "/api/v1/pages",
                json={
                    "space_id": str(spaces[0].id),
                    "title": "Attempt",
                    "template": templates[0].name,
                },
            )
            assert r.status_code == 404, r.text
            assert (await client.get(f"/api/v1/page-spaces/{spaces[0].id}/pages")).json() == []
            for template, expected in [
                (templates[1], "Local Good"),
                (templates[2], "Global Template writer"),
            ]:
                r = await client.post(
                    "/api/v1/pages",
                    json={
                        "space_id": str(spaces[0].id),
                        "title": "Good",
                        "template": template.name,
                    },
                )
                assert r.status_code == 201 and r.json()["body"] == expected, r.text
        await db.rollback()
    await engine.dispose()
