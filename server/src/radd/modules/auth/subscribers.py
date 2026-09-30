from radd.db import SessionLocal

from . import principals, roles


async def ensure_seeded() -> None:
    """Idempotent on-startup ensure: the builtin roles and the built-in accounts
    (the two principals and the Automation account)."""
    async with SessionLocal() as session:
        await roles.ensure_builtin_roles(session)
        await principals.ensure_builtin_accounts(session)
        await session.commit()
