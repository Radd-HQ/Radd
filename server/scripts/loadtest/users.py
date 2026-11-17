"""The people a load test signs in as (RADD-1536): N local Member accounts.

They are ordinary members — a global `Member` grant, no admin — so every
request they make pays for the same visibility and permission work a real
person's does. An admin's requests skip most of it and measure a faster
product than the one people use.

Run with the app's own code against the LOAD database:

    RADD_DATABASE_URL=postgresql+psycopg://radd:radd@127.0.0.1:5458/radd \\
        uv run python scripts/loadtest/users.py --count 200
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from radd.config import settings
from radd.db import SessionLocal
from radd.kernel import import_models
from radd.modules.auth.models import GlobalRoleGrant, Role, User
from radd.modules.auth.security import hash_password
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole, UserSource

EMAIL = "load{index:04d}@load.invalid"
PASSWORD = "load-test-only"


async def ensure(count: int) -> None:
    import_models(settings.modules)
    hashed = hash_password(PASSWORD)  # one hash for all: these are throwaway accounts
    async with SessionLocal() as session:
        member = await session.scalar(select(Role).where(Role.key == BuiltinRoleKey.MEMBER))
        if member is None:
            raise SystemExit("no builtin Member role: start the app once, or run radd.seed")
        emails = [EMAIL.format(index=index) for index in range(count)]
        existing = set(await session.scalars(select(User.email).where(User.email.in_(emails))))
        created = 0
        for index, email in enumerate(emails):
            if email in existing:
                continue
            user = User(
                email=email,
                name=f"Load User {index:04d}",
                password_hash=hashed,
                instance_role=InstanceRole.MEMBER,
                source=UserSource.LOCAL,
            )
            session.add(user)
            await session.flush()
            session.add(GlobalRoleGrant(role_id=member.id, user_id=user.id))
            created += 1
        await session.commit()
    print(f"{created} created, {len(existing)} already there — password {PASSWORD!r}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--count", type=int, default=200)
    asyncio.run(ensure(parser.parse_args().count))
