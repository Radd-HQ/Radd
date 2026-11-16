"""Request IDs, structured logs and /metrics (RADD-1530)."""

import json
import logging

import pytest
from httpx import ASGITransport, AsyncClient

from radd import observability
from radd.app import create_app
from radd.config import settings
from radd.observability import JsonFormatter, RequestIdFilter, accept_request_id, metrics


@pytest.fixture
async def http():
    metrics.reset()
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as client:
        yield client
    metrics.reset()


async def test_every_response_names_its_request_and_a_proxys_id_is_kept(http):
    minted = (await http.get("/health")).headers["x-request-id"]
    assert len(minted) == 32
    kept = await http.get("/health", headers={"X-Request-ID": "edge-proxy-0001"})
    assert kept.headers["x-request-id"] == "edge-proxy-0001"


def test_an_incoming_id_that_is_not_sane_is_replaced_not_trusted():
    """It is written into logs and echoed in a header."""
    for hostile in ("short", "has space in it", "line\nbreak-injected", "x" * 65, "", None):
        assert accept_request_id(hostile) != hostile
    assert accept_request_id("ok-ID_1234.5678") == "ok-ID_1234.5678"


async def test_a_log_line_written_while_serving_carries_that_requests_id(http, caplog):
    seen: list[str | None] = []

    class Capture(logging.Handler):
        def emit(self, record):
            seen.append(getattr(record, "request_id", None))

    handler = Capture()
    handler.addFilter(RequestIdFilter())
    logger = logging.getLogger("radd.client_error")
    logger.addHandler(handler)
    try:
        answer = await http.post(f"{settings.api_prefix}/client-errors", json={"message": "boom"})
    finally:
        logger.removeHandler(handler)
    assert seen == [answer.headers["x-request-id"]]
    assert observability.request_id.get() is None, "the ID leaked out of its request"


def test_json_lines_carry_the_request_id_the_exception_and_structured_extra():
    record = logging.LogRecord("radd.x", logging.ERROR, __file__, 1, "failed for %s", ("RADD-1",), None)
    record.request_id = "abc12345"
    record.client_error = {"route": "/issues/RADD-1"}
    line = json.loads(JsonFormatter().format(record))
    assert line["message"] == "failed for RADD-1" and line["level"] == "ERROR"
    assert line["request_id"] == "abc12345" and line["client_error"] == {"route": "/issues/RADD-1"}
    assert line["time"].endswith("+00:00")
    assert "args" not in line and "pathname" not in line, "the record's own fields are not payload"


async def test_metrics_are_absent_by_default_and_gated_by_the_token(http, monkeypatch):
    assert (await http.get("/metrics")).status_code == 404
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_token", "scrape-secret")
    assert (await http.get("/metrics")).status_code == 401
    assert (await http.get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 401
    ok = await http.get("/metrics", headers={"Authorization": "Bearer scrape-secret"})
    assert ok.status_code == 200 and ok.headers["content-type"].startswith("text/plain")


async def test_requests_are_counted_by_route_template_never_by_path(http, monkeypatch):
    monkeypatch.setattr(settings, "metrics_enabled", True)
    for item in ("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"):
        await http.get(f"{settings.api_prefix}/items/{item}")
    await http.get("/health")
    body = (await http.get("/metrics")).text

    template = "/items/{item_id}"  # the route as declared; the API prefix is a mount, not a label
    assert "11111111" not in body, "an item id became a label: one time series per item"
    counted = [line for line in body.splitlines()
               if line.startswith("radd_http_requests_total") and f'route="{template}"' in line]
    assert len(counted) == 1 and counted[0].endswith(" 2"), counted
    assert f'radd_http_request_duration_seconds_count{{method="GET",route="{template}"}} 2' in body
    assert 'route="/health",status="200"} 1' in body
    assert "radd_event_loop_lag_seconds " in body
    assert "radd_db_pool_connections" in body


def test_the_histogram_is_cumulative():
    metrics.reset()
    metrics.observe("GET", "/x", 200, 0.02)
    metrics.observe("GET", "/x", 200, 3.0)
    buckets = metrics.latency_buckets[("GET", "/x")]
    bounds = (*observability.LATENCY_BUCKETS, float("inf"))
    assert [count for bound, count in zip(bounds, buckets, strict=True) if bound in (0.01, 0.025, 2.5, 5.0)] == [0, 1, 1, 2]
    assert buckets[-1] == 2
    metrics.reset()
