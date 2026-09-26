"""Per-(actor, project) field writability (the SPA's disable-up-front signal).

`fields.service.readonly_field_keys` composes the tested resolution primitives into the exact set the
frontend needs: builtin field NAMES + custom field KEYS the actor may NOT write in a project. DB-backed
but rolled back. Pins the wiring so a locked field is disabled up front instead of erroring on save.
"""

import uuid


from radd.modules.access import service as access
from radd.modules.access.types import Access, GrantSubject
from radd.modules.fields import service as fields_service
from radd.modules.fields.schemas import FieldDefinitionCreate
from radd.modules.fields.types import FieldType
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate

from _factories import make_project


async def _team(db):
    return await teams_service.create_team(db, TeamCreate(name=f"Leads-{uuid.uuid4().hex[:6]}"))


async def _readonly(db, project, *, teams=(), manage=False):
    return set(
        await fields_service.readonly_field_keys(
            db,
            project,
            user_id=uuid.uuid4(),
            role_ids=frozenset(),
            team_ids=frozenset(teams),
            group_ids=frozenset(),
            has_manage=manage,
        )
    )


async def test_readonly_reflects_custom_and_builtin_write_grants(db):
    project = await make_project(db, "FW")
    team = await _team(db)
    tag = uuid.uuid4().hex[:6]

    gated = await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            project_ids=[project.id], key=f"budget_{tag}", name="Budget", type=FieldType.TEXT
        ),
    )
    await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            project_ids=[project.id], key=f"open_{tag}", name="Open", type=FieldType.TEXT
        ),
    )
    # A WRITE grant restricts the custom field + the builtin "priority" to the team's members.
    await access.add_grant(
        db, "field", str(gated.id),
        subject_type=GrantSubject.TEAM, subject_id=team.id,
        access=Access.WRITE.value, project_id=project.id,
    )
    await access.add_grant(
        db, "builtin_field", "priority",
        subject_type=GrantSubject.TEAM, subject_id=team.id,
        access=Access.WRITE.value, project_id=project.id,
    )

    # A user NOT on the team: the gated custom field + "priority" are read-only; the open field isn't.
    without = await _readonly(db, project)
    assert f"budget_{tag}" in without
    assert "priority" in without
    assert f"open_{tag}" not in without

    # A user ON the team can write both → nothing read-only for them.
    member = await _readonly(db, project, teams=[team.id])
    assert f"budget_{tag}" not in member and "priority" not in member

    # RADD-816 (F5.2): `manage` means INSTANCE ADMIN at the callers now — a
    # project manager constructs manage=False and is denied like anyone else.
    admin_view = await _readonly(db, project, manage=True)
    assert f"budget_{tag}" not in admin_view and "priority" not in admin_view


async def test_no_grants_means_nothing_readonly(db):
    project = await make_project(db, "FW")
    tag = uuid.uuid4().hex[:6]
    await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            project_ids=[project.id], key=f"plain_{tag}", name="Plain", type=FieldType.TEXT
        ),
    )
    assert await _readonly(db, project) == set()


async def test_scoped_grant_is_readonly_only_in_its_project(db):
    a = await make_project(db, "FW")
    b = await make_project(db, "FW")
    team = await _team(db)
    tag = uuid.uuid4().hex[:6]
    # A GLOBAL field, but a write grant SCOPED to project A only.
    gated = await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            project_ids=[], key=f"cost_{tag}", name="Cost", type=FieldType.TEXT
        ),
    )
    await access.add_grant(
        db, "field", str(gated.id),
        subject_type=GrantSubject.TEAM, subject_id=team.id,
        access=Access.WRITE.value, project_id=a.id,
    )
    assert f"cost_{tag}" in await _readonly(db, a)  # restricted on A
    assert f"cost_{tag}" not in await _readonly(db, b)  # open on B (out of scope)
