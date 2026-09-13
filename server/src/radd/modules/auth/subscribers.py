from radd.db import SessionLocal

from . import principals, roles


async def ensure_seeded() -> None:
    """Idempotent on-startup ensure: the builtin global admin/member/viewer roles
    exist (spec 86 stage 3 — replaces the retired `workspace.created` hook; the
    seed script and test fixtures call `roles.ensure_builtin_roles` directly)."""
    async with SessionLocal() as session:
        await roles.ensure_builtin_roles(session)
        await principals.ensure_principals(session)
        await session.commit()
