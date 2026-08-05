"""RADD-809 — the inspector explains both halves of the access system.

`permission_sources` gains a SPACE scope, channel provenance (membership /
team / grant) and role backlinks; `access.inspect.subject_access` explains the
spec-92 half (which grant rows reach a subject, with resource labels and the
default-open distinction); teams get the same treatment. All assertions
failed on the pre-change code (the fields/params did not exist).

DB-backed; flushed, never committed.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.access import inspect as access_inspect, service as access_service
from radd.modules.access.types import GrantSubject
from radd.modules.auth import authz, grants as auth_grants, roles as auth_roles
from radd.modules.auth.models import ProjectMember, User
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole
from radd.modules.fields import service as fields_service
from radd.modules.fields.schemas import FieldDefinitionCreate
from radd.modules.fields.types import FieldAccess, FieldType
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import ProjectTeamAttach, TeamCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def member(db) -> User:
    user = User(
        email=f"insp-{uuid.uuid4().hex[:8]}@example.com",
        name="Inspected",
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    await auth_roles.ensure_builtin_roles(db)
    return user


async def _project(db, prefix="IN"):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"{prefix}{uuid.uuid4().hex[:4].upper()}", name="P")
    )


async def _role(db, name, permissions):
    return await auth_roles.create_role(
        db, RoleCreate(key=f"insp{uuid.uuid4().hex[:6]}", name=name, permissions=permissions)
    )


async def test_sources_carry_channel_scope_and_backlink(db, member):
    project = await _project(db)
    role = await _role(db, "Painters", ["item.update"])
    db.add(ProjectMember(project_id=project.id, user_id=member.id, role_id=role.id))
    await db.flush()

    sources = await authz.permission_sources(db, member, project=project)
    row = next(s for s in sources if s.permission == "item.update")
    assert row.kind == "role" and row.role_name == "Painters"
    assert row.role_id == role.id
    assert row.scope == "project" and row.via == "membership"

    baseline_row = next(s for s in sources if s.kind == "baseline")
    baseline_role = await auth_roles.role_by_key(db, BuiltinRoleKey.BASELINE)
    assert baseline_row.role_id == baseline_role.id


async def test_sources_name_the_carrying_team(db, member):
    project = await _project(db)
    role = await _role(db, "Wranglers", ["cycle.create"])
    team = await teams_service.create_team(db, TeamCreate(name=f"T{uuid.uuid4().hex[:6]}"))
    await teams_service.add_team_member(db, team.id, member.id)
    await teams_service.attach_project_team(
        db, project.id, ProjectTeamAttach(team_id=team.id, role_id=role.id)
    )

    sources = await authz.permission_sources(db, member, project=project)
    row = next(s for s in sources if s.permission == "cycle.create")
    assert row.via == "team" and row.via_team == team.name
    assert row.scope == "project"


async def test_sources_resolve_a_space_scope(db, member):
    from radd.modules.pages.models import PageSpace

    # The RADD-808 diagnostic scenario: Baseline narrowed, access via a
    # space-scoped role grant (baseline-first dedupe would otherwise claim
    # page.read for the floor).
    baseline = await auth_roles.role_by_key(db, BuiltinRoleKey.BASELINE)
    baseline.permissions = []
    await db.flush()

    space = PageSpace(name="Render", slug=f"sp{uuid.uuid4().hex[:6]}", position=1)
    db.add(space)
    await db.flush()
    role = await _role(db, "Wiki readers", ["page.read"])
    await auth_grants.create_grant(db, role_id=role.id, user_id=member.id, space_id=space.id)

    global_sources = await authz.permission_sources(db, member)
    assert not any(s.permission == "page.read" and s.kind == "role" for s in global_sources)

    space_sources = await authz.permission_sources(db, member, space_id=space.id)
    row = next(s for s in space_sources if s.permission == "page.read" and s.kind == "role")
    assert row.scope == "space" and row.via == "grant" and row.role_id == role.id


async def test_resource_access_names_subject_label_and_default(db, member):
    project = await _project(db)
    definition = await fields_service.create_field(
        db,
        FieldDefinitionCreate(project_ids=[project.id], key="sal", name="Salary", type=FieldType.TEXT),
    )
    role = await _role(db, "Payroll", [])
    await access_service.add_grant(
        db,
        "field",
        str(definition.id),
        subject_type=GrantSubject.ROLE,
        subject_id=role.id,
        access=FieldAccess.WRITE.value,
        project_id=project.id,
    )
    # The member holds the role via a project membership.
    db.add(ProjectMember(project_id=project.id, user_id=member.id, role_id=role.id))
    await db.flush()

    role_ids = await authz.all_held_role_ids(db, member)
    assert role.id in role_ids
    sections = await access_inspect.subject_access(
        db,
        user_id=member.id,
        role_ids=role_ids,
        role_names={role.id: role.name},
    )
    fields_section = next(s for s in sections if s.resource_type == "field")
    assert fields_section.default_open is True
    row = next(r for r in fields_section.rows if r.resource_id == str(definition.id))
    assert row.resource_label == "Salary"
    assert row.subject_type == "role" and row.subject_name == "Payroll"
    assert row.project_id == project.id and row.project_key == project.key

    # Closed-by-default types report themselves so an empty list reads right.
    views_section = next(s for s in sections if s.resource_type == "view")
    assert views_section.default_open is False and views_section.hierarchical is True


async def test_team_access_reports_attachments_and_grants(db, member):
    project = await _project(db)
    role = await _role(db, "Crew", ["item.read"])
    team = await teams_service.create_team(db, TeamCreate(name=f"T{uuid.uuid4().hex[:6]}"))
    await teams_service.attach_project_team(
        db, project.id, ProjectTeamAttach(team_id=team.id, role_id=role.id)
    )
    wiki_role = await _role(db, "Wiki", ["page.read"])
    await auth_grants.create_grant(db, role_id=wiki_role.id, team_id=team.id)

    atoms = await authz.team_permission_sources(db, team.id)
    attached = next(a for a in atoms if a.permission == "item.read")
    assert attached.via == "attached" and attached.scope == "project"
    assert attached.scope_label == project.key
    granted = next(a for a in atoms if a.permission == "page.read")
    assert granted.via == "grant" and granted.scope == "global"

    # A resource grant naming the team surfaces in the team's resource view.
    definition = await fields_service.create_field(
        db,
        FieldDefinitionCreate(project_ids=[project.id], key="tf", name="TeamField", type=FieldType.TEXT),
    )
    await access_service.add_grant(
        db,
        "field",
        str(definition.id),
        subject_type=GrantSubject.TEAM,
        subject_id=team.id,
        access=FieldAccess.READ.value,
    )
    sections = await access_inspect.subject_access(
        db, team_ids={team.id}, team_names={team.id: team.name}
    )
    fields_section = next(s for s in sections if s.resource_type == "field")
    row = next(r for r in fields_section.rows if r.resource_id == str(definition.id))
    assert row.subject_type == "team" and row.subject_name == team.name
