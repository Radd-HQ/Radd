"""RADD-1304 — one "own ticket" set, and sharing a ticket is a grant.

A reporter holding nothing but the Baseline shares and attaches on THEIR
ticket and is refused on a colleague's; the MCP catalog now shows them the
participant tool (it hid it when the rule was an identity check); and the
three floors carry the same own-ticket set.
"""

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.attachments.parents import binding_for
from radd.modules.auth import roles
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import GlobalRoleGrant, Role, User
from radd.modules.auth.types import (
    BUILTIN_ROLES, OWN_TICKET, SESSION_COOKIE_NAME, BuiltinRoleKey, LoginMethod, expand_permissions,
)
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.mcp.catalog import live_catalog
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate


def test_the_three_floors_share_the_own_ticket_set():
    floors = {spec.key: set(spec.permissions) for spec in BUILTIN_ROLES}
    for key in (BuiltinRoleKey.BASELINE, BuiltinRoleKey.REQUESTER):
        assert set(OWN_TICKET) <= floors[key], key
    contributor = expand_permissions({str(p) for p in floors[BuiltinRoleKey.CONTRIBUTOR]})
    # A contributor comments/attaches on ANY public issue (bare atoms, which
    # cover @own); the rest of the set is held as written.
    assert {"comment.write", "attachment.create", "participant.manage@own",
            "comment.delete@own", "attachment.delete@own"} <= contributor


def test_editing_an_issue_implies_managing_its_participants():
    assert "participant.manage" in expand_permissions({"item.update"})


@pytest.fixture
async def world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        await roles.ensure_builtin_roles(db)
        admin = User(email=f"ot-a-{uuid.uuid4().hex[:6]}@example.com", name="Admin", instance_role="admin")
        reporter = User(email=f"ot-r-{uuid.uuid4().hex[:6]}@example.com", name="Reporter", instance_role="member")
        reader = User(email=f"ot-v-{uuid.uuid4().hex[:6]}@example.com", name="Reader", instance_role="member")
        friend = User(email=f"ot-f-{uuid.uuid4().hex[:6]}@example.com", name="Friend", instance_role="member")
        db.add_all([admin, reporter, reader, friend])
        await db.flush()
        project = await projects.create_project(db, ProjectCreate(key=f"OT{uuid.uuid4().hex[:3].upper()}", name="Own"))
        # The reader can see every issue (Viewer) but holds sharing only @own (Baseline).
        viewer = await db.scalar(select(Role).where(Role.key == BuiltinRoleKey.VIEWER.value))
        db.add(GlobalRoleGrant(role_id=viewer.id, user_id=reader.id, project_id=project.id))
        await db.flush()

        async def issue(reported_by):
            read = await items_service.create_item(
                db, ItemCreate(project_id=project.id, title="t", reporter_id=reported_by.id), admin
            )
            return read

        mine = await issue(reader)
        colleagues = await issue(admin)
        reporters = await issue(reporter)
        app = create_app()

        async def override():
            yield db

        app.dependency_overrides[get_session] = override

        def client_for(user, token):
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1",
                                     cookies={SESSION_COOKIE_NAME: token})

        tokens = {
            u.id: await auth_service.create_session(db, u, method=LoginMethod.PASSWORD_TOTP)
            for u in (reader, reporter)
        }
        yield db, {"reader": reader, "reporter": reporter, "friend": friend}, \
            {"mine": mine, "colleagues": colleagues, "reporters": reporters}, \
            lambda user: client_for(user, tokens[user.id])
        await db.rollback()
    await engine.dispose()


async def test_sharing_is_limited_to_your_own_ticket(world):
    _db, people, issues, client_for = world
    async with client_for(people["reader"]) as client:
        own = await client.post(f"/items/{issues['mine'].id}/participants", json={"user_id": str(people["friend"].id)})
        assert own.status_code == 201, own.text
        theirs = await client.post(f"/items/{issues['colleagues'].id}/participants", json={"user_id": str(people["friend"].id)})
        assert theirs.status_code == 403  # can READ it (Viewer), may not share it
        listed = await client.get(f"/items/{issues['colleagues'].id}/participants")
        assert listed.json()["can_manage"] is False
        listed_own = await client.get(f"/items/{issues['mine'].id}/participants")
        assert listed_own.json()["can_manage"] is True


async def test_a_baseline_reporter_can_attach_to_their_ticket_only(world):
    db, people, issues, _client_for = world
    write = binding_for("item").require_write
    await write(db, people["reader"], issues["mine"].id)  # own: allowed
    with pytest.raises(ForbiddenError):
        await write(db, people["reader"], issues["colleagues"].id)


async def test_the_mcp_catalog_offers_sharing_to_a_baseline_reporter(world):
    """The catalog read the old rule as `item.update` and hid the tool from the
    reporter it was for; the grant is now what both sides read."""
    db, people, _issues, _client_for = world
    names = {tool["name"] for tool in await live_catalog(db, people["reporter"])}
    assert {"add_participant", "list_participants"} <= names
