"""RADD-834 — bulk move re-enters the service path's checks.

`_move_one` used to mutate ORM objects directly, so builtin/custom field
grants, workflow-transition guards and approval consumption never ran on the
move path while running on every single-item edit. These tests pin the three
checks (each failed on the pre-fix code), plus the estimate_points governance
gap and the archived/rank ungrantability invariant that set_archived /
reorder_item silently rely on.

DB-backed (compose Postgres) — flushed, never committed; the session rolls
back at teardown.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ForbiddenError
from radd.modules.access import service as access_service
from radd.modules.access.types import GrantSubject
from radd.modules.auth import roles as auth_roles
from radd.modules.auth.models import GlobalRoleGrant, User
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole
from radd.modules.fields import service as fields_service
from radd.modules.fields.schemas import FieldDefinitionCreate
from radd.modules.fields.types import BuiltinItemField, FieldAccess, FieldType
from radd.modules.items import bulk, service as items
from radd.modules.items.enums import BulkSkipReason
from radd.modules.items.history import item_history
from radd.modules.items.schemas import ItemBulkMove, ItemCreate, ItemUpdate
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope
from radd.modules.workflow import service as workflow, transitions
from radd.modules.workflow.schemas import TransitionCreate, TransitionRule
from radd.modules.workflow.types import TransitionCheck, TransitionMode
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
async def admin(db) -> User:
    user = User(
        email=f"bmg-{uuid.uuid4().hex[:8]}@example.com",
        name="Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _project(db, prefix):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"{prefix}{uuid.uuid4().hex[:4].upper()}", name="P")
    )


async def _member(db, *projects) -> User:
    user = User(
        email=f"bmg-m-{uuid.uuid4().hex[:8]}@example.com",
        name="Member",
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    await auth_roles.ensure_builtin_roles(db)
    role = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    for project in projects:
        db.add(GlobalRoleGrant(project_id=project.id, user_id=user.id, role_id=role.id))
    await db.flush()
    return user


async def _restricting_role(db) -> uuid.UUID:
    """A role nobody in these tests holds — the subject of restricting grants."""
    role = await auth_roles.create_role(
        db, RoleCreate(key=f"leads{uuid.uuid4().hex[:6]}", name="Leads")
    )
    return role.id


async def _restrict_builtin(db, field: str, role_id: uuid.UUID, access=FieldAccess.WRITE):
    await access_service.add_grant(
        db,
        fields_service.BUILTIN_RESOURCE,
        field,
        subject_type=GrantSubject.ROLE,
        subject_id=role_id,
        access=access.value,
    )


async def _states(db, project):
    return {s.name: s for s in await workflow.list_states(db, project.id)}


# --- H1(a): field grants ------------------------------------------------------


async def test_bulk_move_respects_builtin_state_rule(db, admin):
    src = await _project(db, "BMA")
    dst = await _project(db, "BMB")
    member = await _member(db, src, dst)
    await _restrict_builtin(db, BuiltinItemField.STATE.value, await _restricting_role(db))

    item = await items.create_item(db, ItemCreate(project_id=src.id, title="held"), admin)
    # The single-item path refuses this member a state write; the move writes
    # state (the mapped target row) and must refuse identically.
    result = await bulk.bulk_move_items(
        db, ItemBulkMove(item_ids=[item.id], target_project_id=dst.id), member
    )
    assert result.moved == []
    assert result.skipped[0].reason == BulkSkipReason.FORBIDDEN
    assert (await items.get_item(db, item.id, admin)).key.startswith(src.key)


async def test_bulk_move_checks_dropped_custom_field_writability(db, admin):
    src = await _project(db, "BMC")
    dst = await _project(db, "BMD")
    member = await _member(db, src, dst)
    definition = await fields_service.create_field(
        db,
        FieldDefinitionCreate(project_ids=[src.id], key="flavor", name="Flavor", type=FieldType.TEXT),
    )
    item = await items.create_item(
        db,
        ItemCreate(project_id=src.id, title="flavored", custom_fields={"flavor": "salt"}),
        admin,
    )
    # Restrict WRITE on the field to a role the member lacks. Moving to a
    # project without the field DROPS the value — that is a write.
    await access_service.add_grant(
        db,
        "field",
        str(definition.id),
        subject_type=GrantSubject.ROLE,
        subject_id=await _restricting_role(db),
        access=FieldAccess.WRITE.value,
    )
    result = await bulk.bulk_move_items(
        db, ItemBulkMove(item_ids=[item.id], target_project_id=dst.id), member
    )
    assert result.moved == []
    assert result.skipped[0].reason == BulkSkipReason.FORBIDDEN


# --- H1(b): workflow guards ----------------------------------------------------


async def test_bulk_move_runs_wildcard_arrival_guards(db, admin):
    src = await _project(db, "BME")
    dst = await _project(db, "BMF")
    await settings_service.set_value(
        db,
        SettingKey.WORKFLOW_TRANSITION_MODE,
        SettingScope.PROJECT,
        dst.id,
        TransitionMode.GUARDS.value,
    )
    dst_states = await _states(db, dst)
    # A wildcard (from-any) rule into the target's Done — the spec-112 shape.
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=dst.id,
            to_state_id=dst_states["Done"].id,
            rules=[
                TransitionRule(
                    check=TransitionCheck.REQUIRE_FIELD,
                    params={"kind": "builtin", "key": "assignee", "op": "set"},
                )
            ],
        ),
    )
    src_states = await _states(db, src)
    blocked = await items.create_item(
        db, ItemCreate(project_id=src.id, title="unassigned", state_id=src_states["Done"].id), admin
    )
    passing = await items.create_item(
        db,
        ItemCreate(
            project_id=src.id,
            title="assigned",
            state_id=src_states["Done"].id,
            assignee_id=admin.id,
        ),
        admin,
    )
    result = await bulk.bulk_move_items(
        db, ItemBulkMove(item_ids=[blocked.id, passing.id], target_project_id=dst.id), admin
    )
    assert [m.item_id for m in result.moved] == [passing.id]
    assert result.skipped[0].item_id == blocked.id
    assert result.skipped[0].reason == BulkSkipReason.TRANSITION_BLOCKED
    # The blocked item's savepoint rolled back entirely.
    assert (await items.get_item(db, blocked.id, admin)).key.startswith(src.key)


# --- estimate_points is governable --------------------------------------------


async def test_estimate_points_write_rule_enforced(db, admin):
    project = await _project(db, "BMG")
    member = await _member(db, project)
    await _restrict_builtin(db, "estimate_points", await _restricting_role(db))
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="pts"), admin)
    with pytest.raises(ForbiddenError):
        await items.update_item(db, item.id, ItemUpdate(estimate_points=5), member)


async def test_estimate_points_read_rule_blanks(db, admin):
    project = await _project(db, "BMH")
    member = await _member(db, project)
    await _restrict_builtin(
        db, "estimate_points", await _restricting_role(db), access=FieldAccess.READ
    )
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="pts", estimate_points=8), admin
    )
    read = await items.get_item(db, item.id, member)
    assert read.estimate_points is None
    assert (await items.get_item(db, item.id, admin)).estimate_points == 8


# --- H2: history redacts restricted values -------------------------------------


async def test_history_redacts_restricted_custom_field(db, admin):
    project = await _project(db, "BMI")
    member = await _member(db, project)
    definition = await fields_service.create_field(
        db,
        FieldDefinitionCreate(project_ids=[project.id], key="salary", name="Salary", type=FieldType.TEXT),
    )
    await access_service.add_grant(
        db,
        "field",
        str(definition.id),
        subject_type=GrantSubject.ROLE,
        subject_id=await _restricting_role(db),
        access=FieldAccess.READ.value,
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), admin)
    await items.update_item(db, item.id, ItemUpdate(custom_fields={"salary": "9000"}), admin)

    history = await item_history(db, item.id, member)
    change = next(
        c
        for entry in history.entries
        for c in entry.changes
        if c.get("field") == "custom_field" and c.get("key") == "salary"
    )
    # Redacted, not omitted: the fact of the change survives, the values don't.
    assert change.get("redacted") is True
    assert "from" not in change and "to" not in change

    admin_history = await item_history(db, item.id, admin)
    admin_change = next(
        c
        for entry in admin_history.entries
        for c in entry.changes
        if c.get("field") == "custom_field" and c.get("key") == "salary"
    )
    assert admin_change.get("to") == "9000"


async def test_history_redacts_restricted_builtin(db, admin):
    project = await _project(db, "BMJ")
    member = await _member(db, project)
    await _restrict_builtin(
        db, BuiltinItemField.ASSIGNEE.value, await _restricting_role(db), access=FieldAccess.READ
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), admin)
    await items.update_item(db, item.id, ItemUpdate(assignee_id=admin.id), admin)

    history = await item_history(db, item.id, member)
    change = next(
        c for entry in history.entries for c in entry.changes if c.get("field") == "assignee"
    )
    assert change.get("redacted") is True
    assert "from" not in change and "to" not in change


# --- the archived/rank near-miss guard ------------------------------------------


def test_ungoverned_write_paths_stay_ungrantable():
    """set_archived and reorder_item skip _check_builtin_field_rules — sound only
    while `archived`/`rank` cannot carry rules. And every writable ItemUpdate
    field is either mapped into the rules or deliberately exempt, so a new field
    forces a decision here instead of silently escaping governance."""
    from radd.modules.items.service.visibility import _BUILTIN_FIELD_MAP

    builtin_values = {f.value for f in BuiltinItemField}
    assert {"archived", "rank"}.isdisjoint(builtin_values)
    assert set(_BUILTIN_FIELD_MAP.values()) <= builtin_values
    unmapped = set(ItemUpdate.model_fields) - set(_BUILTIN_FIELD_MAP)
    # updated_at: import metadata, project.manage-gated. type_id: the issue-type
    # axis has no rule row by design (spec 51). custom_fields: governed by
    # writable_check, not the builtin map.
    assert unmapped == {"updated_at", "type_id", "custom_fields"}
