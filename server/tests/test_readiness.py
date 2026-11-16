"""/ready asks the database; /health does not (RADD-1534).

The chart probed /health for readiness, and /health answers 200 with the
database unreachable, so a pod that could serve nothing kept receiving traffic.
"""

from httpx import ASGITransport, AsyncClient

from radd import db as radd_db
from radd.app import create_app


async def test_ready_is_200_with_a_database_and_503_without(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as http:
        assert (await http.get("/ready")).status_code == 200

        class Unreachable:
            def connect(self):
                raise ConnectionRefusedError("database is down")

        monkeypatch.setattr(radd_db, "engine", Unreachable())
        down = await http.get("/ready")
        assert down.status_code == 503
        assert down.json()["database"] == "ConnectionRefusedError"
        # Liveness must NOT follow the database down: a restart would not help.
        assert (await http.get("/health")).status_code == 200
