"""Idempotent bootstrap: instance-admin user + global builtin roles + default
work categories (spec 86 — the workspace entity is gone; users are users OF THE
SERVER, any active user holds the global member floor).

Run:  uv run python -m radd.seed --email admin@example.com --password change-me [--name Admin]
Env fallbacks: RADD_SEED_EMAIL, RADD_SEED_PASSWORD, RADD_SEED_NAME.
"""

import argparse
import asyncio
import os

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.kernel import import_models
from radd.modules.auth import principals, roles, service as auth
from radd.modules.auth.models import User
from radd.modules.auth.security import hash_password
from radd.modules.auth.schemas import UserCreate
from radd.modules.auth.types import InstanceRole
from radd.modules.timelogging import categories


async def seed(email: str, password: str, name: str) -> None:
    import_models(settings.modules)
    async with SessionLocal() as session:
        await _ensure_admin_user(session, email, password, name)
        # Idempotent: mirrors the startup-ensure paths (the retired
        # workspace.created hook seeded these) so a fresh DB is usable at once.
        await roles.ensure_builtin_roles(session)
        await principals.ensure_principals(session)
        await categories.ensure_default_categories(session)
        await session.commit()


async def _ensure_admin_user(
    session: AsyncSession, email: str, password: str, name: str
) -> User:
    user = await auth.get_user_by_email(session, email)
    if user is not None:
        # Converge, don't just reuse: the seed's password is authoritative for the seed user.
        user.password_hash = hash_password(password)
        user.instance_role = InstanceRole.ADMIN.value
        print(f"user {user.email} already exists — password and admin role converged")
        return user
    data = UserCreate(email=email, name=name, password=password, instance_role=InstanceRole.ADMIN)
    user = await auth.create_user(session, data)
    print(f"created instance-admin user {user.email}")
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=os.environ.get("RADD_SEED_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("RADD_SEED_PASSWORD"))
    parser.add_argument("--name", default=os.environ.get("RADD_SEED_NAME", "Admin"))
    args = parser.parse_args()
    if not args.email or not args.password:
        parser.error(
            "--email and --password are required (or RADD_SEED_EMAIL / RADD_SEED_PASSWORD)"
        )
    asyncio.run(seed(args.email, args.password, args.name))


if __name__ == "__main__":
    main()
