"""RADD-825 — the Baseline pre-flight report.

The report resolves every active human account under the STORED floor and the
PROPOSED one through the real resolvers and diffs — who loses what, and where
item read survives via a project-scoped source. Pinned here: the loss shows
the right people, explicit grants exempt, the narrowed/removed classification,
and the report leaving the session's floor memo exactly as it found it.

Rolled-back transactions on the compose DB.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth import authz, preflight, roles as auth_roles
from radd.modules.auth.models import ProjectMember, User
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole, Permission

# Side effect: the workflow module's project.created hook seeds default states.
from radd.modules import workflow as _workflow  # noqa: F401
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


async def _user(db, name, *, admin=False) -> User:
    user = User(
        email=f"pf-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=(InstanceRole.ADMIN if admin else InstanceRole.MEMBER).value,
    )
    db.add(user)
    await db.flush()
    return user


async def _widen_baseline(db) -> None:
    """Session-locally restore the pre-flip floor, so the report has the
    narrowing to measure. Rolled back with everything else."""
    await auth_roles.ensure_builtin_roles(db)
    baseline = await auth_roles.role_by_key(db, BuiltinRoleKey.BASELINE.value)
    baseline.permissions = [str(Permission.ITEM_READ), str(Permission.PAGE_READ)]
    await db.flush()
    authz.forget_baseline(db)


async def test_report_names_who_loses_and_where(db):
    await _widen_baseline(db)
    floor_only = await _user(db, "Floor Only")
    granted = await _user(db, "Has A Role")
    admin = await _user(db, "Admin", admin=True)
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"PF{uuid.uuid4().hex[:4].upper()}", name="Pre")
    )
    role = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"pf{uuid.uuid4().hex[:6]}", name="Reader",
            permissions=[Permission.ITEM_READ, Permission.PAGE_READ],
        ),
    )
    db.add(ProjectMember(project_id=project.id, user_id=granted.id, role_id=role.id))
    await db.flush()

    report = await preflight.baseline_preflight(
        db, ["item.read@own"]
    )

    by_id = {row.user_id: row for row in report.rows}
    # The floor-only user loses both reads globally, retains nowhere.
    assert floor_only.id in by_id
    row = by_id[floor_only.id]
    assert str(Permission.ITEM_READ) in row.lost
    assert str(Permission.PAGE_READ) in row.lost
    assert project.key not in row.retained_project_keys
    assert row.lost_project_count >= 1
    # The granted user loses page.read GLOBALLY but keeps the project.
    assert granted.id in by_id
    assert project.key in by_id[granted.id].retained_project_keys
    # Admins resolve to everything in both worlds — never in the report.
    assert admin.id not in by_id
    assert report.users_affected >= 2
    assert report.projects_affected >= 1


async def test_narrowed_vs_removed_classification(db):
    await _widen_baseline(db)
    report = await preflight.baseline_preflight(db, ["item.read@own"])
    # item.read survives as @own → narrowed; page.read has no form left.
    assert str(Permission.ITEM_READ) in report.narrowed
    assert str(Permission.PAGE_READ) in report.removed


async def test_report_leaves_no_fingerprints(db):
    """After the run, the session answers with the STORED floor again — the
    proposed world must not leak into later resolutions."""
    await _widen_baseline(db)
    before = await authz.baseline_permissions(db)
    await preflight.baseline_preflight(db, ["item.read@own"])
    assert await authz.baseline_permissions(db) == before


async def test_unknown_atom_rejected_like_role_edits():
    from pydantic import ValidationError

    from radd.modules.auth.schemas import BaselinePreflightRequest

    with pytest.raises(ValidationError):
        BaselinePreflightRequest(permissions=["item.launch"])
    ok = BaselinePreflightRequest(permissions=["item.read@own"])
    assert ok.permissions == ["item.read@own"]
