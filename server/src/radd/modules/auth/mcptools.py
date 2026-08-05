"""The directory + service-account MCP tools (spec 114), declared by their
owner (RADD-889).

Moved verbatim from mcp/tools.py. Each handler carries its own global
`authz.require` — exactly the pre-move enforcement — so `kernel_enforced=False`
and the spec's `permission` drives the spec-114 caller filter only.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel.mcptools import limit_arg, limit_property, object_schema
from radd.kernel.specs import McpToolSpec

from . import authz, service as auth_service, service_accounts
from .models import User
from .schemas import ServiceAccountCreate
from .types import Permission


async def _list_users(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    await authz.require(session, actor, Permission.USER_MANAGE)
    users = await auth_service.list_users(session, q=args.get("q") or None)
    return [
        {"id": str(u.id), "email": u.email, "name": u.name, "active": u.active,
         "instance_role": u.instance_role, "source": u.source}
        for u in users[: limit_arg(args)]
    ]


async def _list_service_accounts(
    session: AsyncSession, actor: User, args: Mapping[str, Any]
) -> Any:
    await authz.require(session, actor, Permission.GLOBAL_MANAGE)
    accounts = await service_accounts.list_accounts(session)
    return [
        {
            "id": str(a.id),
            "name": a.name,
            "email": a.email,
            "active": a.active,
            "keys": await service_accounts.token_count(session, a.id),
        }
        for a in accounts
    ]


async def _create_service_account(
    session: AsyncSession, actor: User, args: Mapping[str, Any]
) -> Any:
    await authz.require(session, actor, Permission.SERVICE_ACCOUNT_CREATE)
    account = await service_accounts.create_account(
        session,
        ServiceAccountCreate(
            name=str(args["name"]), description=str(args.get("description") or "")
        ),
        actor_id=actor.id,
    )
    return {"id": str(account.id), "name": account.name, "email": account.email}


LIST_USERS = McpToolSpec(
    name="list_users",
    description="Directory of accounts (admin).",
    input_schema=object_schema(
        {"q": {"type": "string", "description": "Substring of email or name."},
         "limit": limit_property()},
        [],
    ),
    handler=_list_users,
    permission=Permission.USER_MANAGE,
    kernel_enforced=False,
)

LIST_SERVICE_ACCOUNTS = McpToolSpec(
    name="list_service_accounts",
    description="Service accounts and their key counts (admin).",
    input_schema=object_schema({}, []),
    handler=_list_service_accounts,
    permission=Permission.GLOBAL_MANAGE,
    kernel_enforced=False,
)

CREATE_SERVICE_ACCOUNT = McpToolSpec(
    name="create_service_account",
    description="Create a service account — a principal that authenticates by API "
    "key only. Keys are minted separately (admin).",
    input_schema=object_schema(
        {"name": {"type": "string"}, "description": {"type": "string"}}, ["name"]
    ),
    handler=_create_service_account,
    permission=Permission.SERVICE_ACCOUNT_CREATE,
    kernel_enforced=False,
)

MCP_TOOLS = (LIST_USERS, LIST_SERVICE_ACCOUNTS, CREATE_SERVICE_ACCOUNT)
