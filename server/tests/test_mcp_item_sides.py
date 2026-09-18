"""The item's side panels over MCP — participants (RADD-1236, radd-hq/radd#8)
and related links (RADD-1239, radd-hq/radd#11) — by key, email, team name and
URL: never a row id an agent would first have to fetch.

DB-backed, flushed never committed.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.kernel import registries
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.mcp import tools
from radd.modules.mcp.catalog import registry_catalog
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, role: InstanceRole, name: str = "Side Tester") -> User:
    user = User(
        email=f"side-{uuid.uuid4().hex[:8]}@example.com", name=name, instance_role=role.value
    )
    db.add(user)
    await db.flush()
    return user


async def _item(db, actor):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SD{uuid.uuid4().hex[:4].upper()}", name="Sides")
    )
    return await items.create_item(db, ItemCreate(project_id=project.id, title="the item"), actor)


def test_the_six_tools_are_in_the_registry_catalog():
    names = {t["name"] for t in registry_catalog(frozenset())}
    assert {
        "list_participants", "add_participant", "remove_participant",
        "list_related_links", "add_related_link", "remove_related_link",
    } <= names
    assert registries.mcp_tools["add_participant"].input_schema["additionalProperties"] is False


async def test_participants_by_email_and_team_name_round_trip(db):
    admin = await _user(db, InstanceRole.ADMIN)
    colleague = await _user(db, InstanceRole.MEMBER, name="Colleague")
    team = await teams_service.create_team(db, TeamCreate(name=f"Desk {uuid.uuid4().hex[:6]}"))
    item = await _item(db, admin)

    added = await tools.call_tool(db, admin, "add_participant", {"key": item.key, "email": colleague.email})
    assert added["added"]["kind"] == "user" and added["added"]["email"] == colleague.email
    # Names are matched case-insensitively — an agent types what it read.
    await tools.call_tool(db, admin, "add_participant", {"key": item.key, "team": team.name.upper()})

    listed = await tools.call_tool(db, admin, "list_participants", {"key": item.key})
    assert listed["can_manage"] is True
    assert {(p["kind"], p["name"]) for p in listed["participants"]} == {
        ("user", "Colleague"), ("team", team.name),
    }
    # The assignee is untouched — that misuse is what the tools replace.
    read = await items.get_item_by_key(db, item.key, actor=admin)
    assert read.assignee is None

    with pytest.raises(ConflictError):
        await tools.call_tool(db, admin, "add_participant", {"key": item.key, "email": colleague.email})

    removed = await tools.call_tool(db, admin, "remove_participant", {"key": item.key, "team": team.name})
    assert removed["removed"]["kind"] == "team"
    listed = await tools.call_tool(db, admin, "list_participants", {"key": item.key})
    assert [p["email"] for p in listed["participants"]] == [colleague.email]


async def test_participant_errors_name_the_cause(db):
    admin = await _user(db, InstanceRole.ADMIN)
    member = await _user(db, InstanceRole.MEMBER)
    item = await _item(db, admin)
    with pytest.raises(NotFoundError):
        await tools.call_tool(db, admin, "add_participant", {"key": item.key, "email": "nobody@example.com"})
    with pytest.raises(NotFoundError):
        await tools.call_tool(db, admin, "remove_participant", {"key": item.key, "email": member.email})
    with pytest.raises(ValueError):
        await tools.call_tool(db, admin, "add_participant", {"key": item.key})
    # A member with no standing on the project cannot even see the item (spec
    # 121 answers "not found" rather than confirming it exists); a member who
    # can see it but holds no item.update and is not the reporter is refused by
    # the service's own gate. Either way the refusal is the seam's, not a
    # blanket kernel gate that would also refuse the reporter.
    with pytest.raises((ForbiddenError, NotFoundError)):
        await tools.call_tool(db, member, "add_participant", {"key": item.key, "email": admin.email})


async def test_related_links_by_url_round_trip(db):
    admin = await _user(db, InstanceRole.ADMIN)
    member = await _user(db, InstanceRole.MEMBER)
    item = await _item(db, admin)
    mr = "https://gitlab.example.com/infra/awx/-/merge_requests/14"

    added = await tools.call_tool(
        db, admin, "add_related_link", {"key": item.key, "url": mr, "title": "awx !14"}
    )
    assert added["added"]["url"] == mr and added["added"]["category"] == "external"
    await tools.call_tool(
        db, admin, "add_related_link", {"key": item.key, "url": "https://docs.example.com/x", "category": "document"}
    )
    listed = await tools.call_tool(db, admin, "list_related_links", {"key": item.key})
    assert sorted(link["category"] for link in listed["links"]) == ["document", "external"]

    with pytest.raises((ForbiddenError, NotFoundError)):
        await tools.call_tool(db, member, "add_related_link", {"key": item.key, "url": "https://x.example"})
    with pytest.raises(NotFoundError):
        await tools.call_tool(db, admin, "remove_related_link", {"key": item.key, "url": "https://nope.example"})

    removed = await tools.call_tool(db, admin, "remove_related_link", {"key": item.key, "url": mr})
    assert removed["removed"]["title"] == "awx !14"
    listed = await tools.call_tool(db, admin, "list_related_links", {"key": item.key})
    assert [link["url"] for link in listed["links"]] == ["https://docs.example.com/x"]
