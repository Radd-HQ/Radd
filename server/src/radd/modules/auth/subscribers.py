from radd.db import SessionLocal

from . import principals, roles


async def ensure_seeded() -> None:
    """Idempotent on-startup ensure: the builtin roles and the principal rows."""
    async with SessionLocal() as session:
        await roles.ensure_builtin_roles(session)
        await principals.ensure_principals(session)
        await session.commit()
