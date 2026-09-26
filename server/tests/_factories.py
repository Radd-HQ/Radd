"""Rows the DB-backed tests share. Each flushes, never commits."""

import uuid

from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


async def make_user(db, *, role=InstanceRole.MEMBER, name="Tester", email=None, **fields) -> User:
    """An account with a unique example.com address unless `email` is given."""
    user = User(
        email=email or f"user-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole(role).value,
        **fields,
    )
    db.add(user)
    await db.flush()
    return user


async def make_project(db, prefix="P", name=None, actor=None):
    """A project keyed `<prefix><hex>` (a key holds at most 10 characters)."""
    key = f"{prefix}{uuid.uuid4().hex[: min(6, 10 - len(prefix))].upper()}"
    return await projects_service.create_project(
        db, ProjectCreate(key=key, name=name or prefix), actor_id=actor.id if actor else None
    )
