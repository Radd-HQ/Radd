"""Service directories bound data and count queries without broadening credential authority."""

import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.clock import utcnow
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import account_directory, mcptools, service as auth
from radd.modules.auth.models import ApiToken, User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.auth.types import LoginMethod


@pytest.fixture
async def world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        admin = User(
            name="Directory admin", email=uuid.uuid4().hex + "@test.invalid", instance_role="admin"
        )
        prefix = uuid.uuid4().hex[:10]
        accounts = [
            User(
                name=f"{prefix} account {i:03}",
                email=f"{prefix}-{i}@test.invalid",
                source="service",
                active=i != 125,
            )
            for i in range(126)
        ]
        db.add_all([admin, *accounts])
        await db.flush()
        now = utcnow().replace(tzinfo=None)
        keys = [
            ApiToken(
                user_id=accounts[-1].id,
                name=f"Key {i:03}",
                token_hash=uuid.uuid4().hex,
                prefix_display=f"prefix{i:03}",
                scopes={
                    "global": ["item.read"],
                    "projects": {str(uuid.uuid4()): ["item.read"] for _ in range(126)},
                }
                if i % 3 == 0
                else {}
                if i % 3 == 1
                else None,
                created_at=now,
                expires_at=now - timedelta(days=1) if i == 125 else None,
            )
            for i in range(126)
        ]
        keys[103].name = "Literal %_ key"
        db.add_all(keys)
        _, key = await auth.create_api_token(
            db, admin, TokenCreate(name="Restricted admin", scopes={})
        )
        _, allowed_key = await auth.create_api_token(
            db, admin, TokenCreate(name="Read admin", scopes={"global": ["global.manage"]})
        )
        app = create_app()

        async def override():
            yield db

        app.dependency_overrides[get_session] = override
        cookie = await auth.create_session(db, admin, method=LoginMethod.PASSWORD)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"radd_session": cookie},
        ) as client:
            yield db, client, admin, accounts, keys, key, allowed_key, prefix
        await db.rollback()
    await engine.dispose()


async def test_account_windows_batch_counts_and_mcp_limits(world):
    db, client, admin, accounts, keys, _, _, prefix = world
    statements = []

    def capture(conn, cursor, sql, parameters, context, executemany):
        statements.append(sql)

    event.listen(db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        seen = []
        for offset, size in [(0, 50), (50, 50), (100, 26)]:
            response = await client.get(
                "/api/v1/service-accounts", params={"q": prefix, "limit": 50, "offset": offset}
            )
            assert response.status_code == 200, response.text
            assert response.headers["X-Total-Count"] == "126" and len(response.json()) == size
            seen.extend(response.json())
        assert [r["id"] for r in seen] == [str(a.id) for a in accounts]
        assert [r["token_count"] for r in seen] == [0] * 125 + [126]
        assert not seen[-1]["active"]
        # Exactly one grouped token-count SELECT per account window; no token hashes/scopes.
        counts = [s for s in statements if "api_tokens.user_id, count(" in s]
        assert len(counts) == 3 and all("GROUP BY api_tokens.user_id" in s for s in counts)
        assert not any("api_tokens.token_hash" in s for s in counts)
    finally:
        event.remove(db.bind.sync_engine, "before_cursor_execute", capture)
    complete = await client.get("/api/v1/service-accounts", params={"q": prefix})
    assert len(complete.json()) == 126
    direct = await client.get("/api/v1/service-accounts/" + str(accounts[-1].id))
    assert direct.json() == seen[-1]
    for args, size in [({"q": prefix}, 25), ({"q": prefix, "limit": 50, "offset": 100}, 26)]:
        rows = await mcptools._list_service_accounts(db, admin, args)
        assert len(rows) == size
    assert (
        await client.get("/api/v1/service-accounts", params={"q": accounts[-1].email, "limit": 50})
    ).headers["X-Total-Count"] == "1"
    accounts[-1].name = prefix + " literal %_"
    await db.flush()
    assert (await client.get("/api/v1/service-accounts", params={"q": "%_", "limit": 50})).headers[
        "X-Total-Count"
    ] == "1"


async def test_key_windows_are_lean_stable_expired_and_revoke_recovers(world):
    db, client, _, accounts, keys, _, _, _ = world
    path = "/api/v1/service-accounts/" + str(accounts[-1].id) + "/keys"
    seen = []
    for offset, size in [(0, 50), (50, 50), (100, 26)]:
        response = await client.get(path + "/directory", params={"offset": offset})
        assert response.status_code == 200, response.text
        assert response.headers["X-Total-Count"] == "126" and len(response.json()) == size
        seen.extend(response.json())
    assert [r["id"] for r in seen] == [str(k.id) for k in sorted(keys, key=lambda k: k.id)]
    assert all("scopes" not in r and "token_hash" not in r for r in seen)
    for row in seen:
        key = next(k for k in keys if str(k.id) == row["id"])
        assert row["restricted"] == (key.scopes is not None)
        assert row["global_count"] == len((key.scopes or {}).get("global", []))
        assert row["project_count"] == len((key.scopes or {}).get("projects", {}))
    assert next(r for r in seen if r["id"] == str(keys[-1].id))["expires_at"]
    response = await client.get(path + "/directory", params={"q": "%_"})
    assert response.headers["X-Total-Count"] == "1" and response.json()[0]["id"] == str(
        keys[103].id
    )
    response = await client.get(path)
    assert len(response.json()) == 126 and any(r["scopes"] for r in response.json())
    # Revoke only the selected key; every off-page key survives, and totals update.
    assert (await client.delete(path + "/" + str(keys[103].id))).status_code == 204
    assert (await client.get(path + "/directory", params={"q": "%_"})).headers[
        "X-Total-Count"
    ] == "0"
    assert (await account_directory.by_id(db, accounts[-1].id)).token_count == 125
    assert (
        len(list(await db.scalars(select(ApiToken.id).where(ApiToken.user_id == accounts[-1].id))))
        == 125
    )


async def test_directory_gates_credential_intersection_and_bounds(world):
    _, client, admin, accounts, _, restricted, allowed, _ = world
    base = "/api/v1/service-accounts"
    for params in [{"limit": 201}, {"offset": -1}, {"q": "x" * 201}]:
        assert (await client.get(base, params=params)).status_code == 422
        assert (
            await client.get(base + "/" + str(accounts[-1].id) + "/keys/directory", params=params)
        ).status_code == 422
    for id in [uuid.uuid4(), admin.id]:
        assert (await client.get(base + "/" + str(id))).status_code == 404
        assert (await client.get(base + "/" + str(id) + "/keys/directory")).status_code == 404
    client.cookies.clear()
    client.headers["Authorization"] = "Bearer " + restricted
    for path in [
        base,
        base + "/" + str(accounts[-1].id),
        base + "/" + str(accounts[-1].id) + "/keys/directory",
    ]:
        assert (await client.get(path)).status_code == 403
    client.headers["Authorization"] = "Bearer " + allowed
    assert (await client.get(base, params={"limit": 50})).status_code == 200
    assert (
        await client.get(base + "/" + str(accounts[-1].id) + "/keys/directory")
    ).status_code == 200
    assert (
        await client.post(
            base + "/" + str(accounts[-1].id) + "/keys", json={"name": "No key delegation"}
        )
    ).status_code == 403


async def test_key_permission_vocabulary_without_issue_readership(world):
    from radd.modules.auth import roles
    from radd.modules.auth.models import GlobalRoleGrant, Role
    from radd.modules.auth.types import BuiltinRoleKey

    db, client, _, _, _, restricted, _, _ = world
    baseline = await roles.role_by_key(db, BuiltinRoleKey.BASELINE)
    baseline.permissions = []
    manager = User(name="Key manager", email=uuid.uuid4().hex + "@test.invalid")
    role = Role(key=uuid.uuid4().hex, name="Key management only", permissions=["service_account.update"])
    db.add_all([manager, role])
    await db.flush()
    db.add(GlobalRoleGrant(user_id=manager.id, role_id=role.id))
    cookie = await auth.create_session(db, manager, method=LoginMethod.PASSWORD)
    client.cookies.set("radd_session", cookie)
    db.info.clear()
    assert (await client.get("/api/v1/projects")).json() == []
    vocabulary = await client.get("/api/v1/permissions")
    assert vocabulary.status_code == 200
    assert any(p["key"] == "item.read" for p in vocabulary.json())
    # The vocabulary exception does not authorize service-account data reads.
    assert (await client.get("/api/v1/service-accounts", params={"limit": 50})).status_code == 403
    client.cookies.clear()
    client.headers["Authorization"] = "Bearer " + restricted
    assert (await client.get("/api/v1/permissions")).status_code == 403
