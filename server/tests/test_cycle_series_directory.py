"""Recurring configuration remains searchable and permission-gated before paging."""
import uuid

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import service as auth
from radd.modules.auth.models import User, Role, GlobalRoleGrant
from radd.modules.auth.types import SESSION_COOKIE_NAME
from radd.modules.auth.schemas import TokenCreate
from radd.modules.cycles.models import CycleSeries
from radd.modules.auth.types import LoginMethod


async def test_series_windows_search_and_admission():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        reader = User(email=f"series-reader-{uuid.uuid4()}@test.invalid", name="Series reader", instance_role="member")
        role = Role(key=f"series-{uuid.uuid4().hex[:8]}", name="Read cycles", permissions=["cycle.read"])
        db.add_all([reader, role])
        await db.flush()
        db.add(GlobalRoleGrant(user_id=reader.id, role_id=role.id))
        prefix = f"Series {uuid.uuid4().hex[:8]}"
        rows = [CycleSeries(label=f"{prefix} {i:03}", drafts_ahead=0, next_number=i+1) for i in range(126)]
        literal = CycleSeries(label=prefix + " %_", drafts_ahead=0, next_number=1)
        db.add_all([*rows, literal])
        cookie = await auth.create_session(db, reader, method=LoginMethod.PASSWORD)
        _, limited_token = await auth.create_api_token(db, reader, TokenCreate(name="No cycle access", scopes={}))
        await db.flush()
        async def session_override():
            yield db
        app = create_app()
        app.dependency_overrides[get_session] = session_override
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                     cookies={SESSION_COOKIE_NAME: cookie}) as client:
            seen = []
            for offset, size in [(0, 50), (50, 50), (100, 27)]:
                response = await client.get("/api/v1/cycle-series", params={"q": prefix, "limit": 50, "offset": offset})
                assert response.status_code == 200, response.text
                assert int(response.headers["X-Total-Count"]) == 127
                assert len(response.json()) == size
                seen.extend(row["id"] for row in response.json())
            assert len(seen) == len(set(seen))
            assert set(seen) == {str(row.id) for row in [*rows, literal]}
            legacy = await client.get("/api/v1/cycle-series", params={"q": prefix})
            assert [row["id"] for row in legacy.json()] == seen
            for q, expected in [(f"  {prefix.lower()} 125  ", rows[125]), ("%_", literal)]:
                response = await client.get("/api/v1/cycle-series", params={"q": q, "limit": 1})
                assert [row["id"] for row in response.json()] == [str(expected.id)]
                assert response.headers["X-Total-Count"] == "1"
            response = await client.get("/api/v1/cycle-series", params={"q": prefix, "limit": 50, "offset": 200})
            assert response.json() == [] and response.headers["X-Total-Count"] == "127"
            for params in [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"q": "x" * 201}]:
                assert (await client.get("/api/v1/cycle-series", params=params)).status_code == 422
            assert (await client.patch(f"/api/v1/cycle-series/{rows[-1].id}", json={"drafts_ahead": 2})).status_code == 403
            assert (await client.delete(f"/api/v1/cycle-series/{rows[-1].id}")).status_code == 403
            await client.post("/api/v1/auth/logout")
            client.cookies.clear()
            client.headers["Authorization"] = f"Bearer {limited_token}"
            response = await client.get("/api/v1/cycle-series", params={"q": prefix, "limit": 50})
            assert response.status_code == 200 and response.json() == []
            assert response.headers["X-Total-Count"] == "0"
        await db.rollback()
    await engine.dispose()
