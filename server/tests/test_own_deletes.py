"""Author-own deletes are GRANTS now (RADD-816 / Q4).

The hardcoded "author deletes own" checks are gone; the right is the
Baseline's `comment.delete@own` / `worklog.delete@own` grants, resolved
through the relation machinery — which makes it inspector-explainable and,
for the first time, REVOCABLE. Both directions are pinned: the grant works,
and emptying the Baseline takes it away (inexpressible before this change).

Rolled-back transactions on the compose DB.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ForbiddenError
from radd.modules.auth import authz, roles as auth_roles
from radd.modules.auth.models import GlobalRoleGrant, User
from radd.modules.auth.types import BuiltinRoleKey, Permission

# Side effect: workflow's project.created hook seeds default states.
from radd.modules import workflow as _workflow  # noqa: F401
from radd.modules.comments import service as comments
from radd.modules.comments.schemas import CommentCreate
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
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
async def rig(db):
    admin = User(
        email=f"od-{uuid.uuid4().hex[:8]}@example.com", name="OD Admin", instance_role="admin"
    )
    author = User(
        email=f"od-{uuid.uuid4().hex[:8]}@example.com", name="Author", instance_role="member"
    )
    db.add_all([admin, author])
    await db.flush()
    await auth_roles.ensure_builtin_roles(db)
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"OD{uuid.uuid4().hex[:4].upper()}", name="O")
    )
    member_role = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    db.add(GlobalRoleGrant(project_id=project.id, user_id=author.id, role_id=member_role.id))
    await db.flush()
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="own-delete rig"), admin
    )
    comment = await comments.create_comment(
        db, item.id, CommentCreate(body="mine to take back"), author
    )
    return admin, author, project, item, comment


async def test_author_deletes_own_comment_via_the_baseline_grant(db, rig):
    _admin, author, _project, _item, comment = rig
    await comments.delete_comment(db, comment.id, author)


async def test_non_author_without_the_atom_is_refused(db, rig):
    _admin, _author, project, _item, comment = rig
    stranger = User(
        email=f"od-{uuid.uuid4().hex[:8]}@example.com", name="Stranger", instance_role="member"
    )
    db.add(stranger)
    await db.flush()
    member_role = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    db.add(GlobalRoleGrant(project_id=project.id, user_id=stranger.id, role_id=member_role.id))
    await db.flush()
    with pytest.raises(ForbiddenError):
        await comments.delete_comment(db, comment.id, stranger)


async def test_revoking_the_baseline_grant_takes_own_delete_away(db, rig):
    """The point of Q4: the right is a GRANT, so an operator can remove it —
    inexpressible while the author check was hardcoded."""
    _admin, author, _project, _item, comment = rig
    baseline = await auth_roles.role_by_key(db, BuiltinRoleKey.BASELINE)
    baseline.permissions = [
        p for p in baseline.permissions if p != "comment.delete@own"
    ]
    await db.flush()
    authz.forget_baseline(db)
    with pytest.raises(ForbiddenError):
        await comments.delete_comment(db, comment.id, author)
