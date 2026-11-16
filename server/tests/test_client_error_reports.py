"""The browser's error reports reach the server log, bounded (RADD-1528)."""

import logging

import pytest
from httpx import ASGITransport, AsyncClient

from radd.app import create_app
from radd.config import settings
from radd.modules.diagnostics import limiter


@pytest.fixture
async def http():
    limiter.reset()
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as client:
        yield client
    limiter.reset()


async def test_a_report_becomes_one_structured_log_line_without_signing_in(http, caplog):
    with caplog.at_level(logging.ERROR, logger="radd.client_error"):
        answer = await http.post(
            f"{settings.api_prefix}/client-errors",
            json={"message": "boom", "stack": "at render", "route": "/issues/RADD-1",
                  "source": "boundary", "build": "0.53.0"},
        )
    assert answer.status_code == 204
    [record] = [r for r in caplog.records if r.name == "radd.client_error"]
    assert record.client_error["message"] == "boom"
    assert record.client_error["route"] == "/issues/RADD-1"
    assert record.client_error["build"] == "0.53.0"
    assert record.client_error["user_id"] is None  # the login page can crash too


async def test_an_oversized_report_is_refused(http):
    answer = await http.post(
        f"{settings.api_prefix}/client-errors",
        json={"message": "x", "stack": "s" * (settings.client_error_max_chars + 1)},
    )
    assert answer.status_code == 422


async def test_a_render_loop_cannot_fill_the_log(http, caplog, monkeypatch):
    monkeypatch.setattr(settings, "client_error_reports_per_minute", 3)
    with caplog.at_level(logging.ERROR, logger="radd.client_error"):
        codes = [
            (await http.post(f"{settings.api_prefix}/client-errors", json={"message": "loop"})).status_code
            for _ in range(5)
        ]
    assert codes == [204, 204, 204, 429, 429]
    assert len([r for r in caplog.records if r.name == "radd.client_error"]) == 3


def test_the_allowance_refills_after_the_window():
    limiter.reset()
    allowance = settings.client_error_reports_per_minute
    assert all(limiter.admit("a", now=0.0) for _ in range(allowance))
    assert not limiter.admit("a", now=1.0)
    assert limiter.admit("b", now=1.0), "one address must not spend another's allowance"
    assert limiter.admit("a", now=61.0)
    limiter.reset()
