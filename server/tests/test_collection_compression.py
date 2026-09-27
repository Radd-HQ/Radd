import gzip

import pytest

from radd.collection_compression import CollectionCompressionMiddleware
from radd.config import settings
from radd.kernel.registry import registries
from radd.kernel.specs import ViewListSpec, ViewTypeSpec

#: A list-surface view type as a plugin registers one (RADD-1427: the slas queue's
#: path used to be a literal here and in the middleware).
FIXTURE_TYPE = ViewTypeSpec(
    key="fixture.rows", label="Fixture rows", list_surface=ViewListSpec(rows_path="/fixture-rows")
)


@pytest.fixture
def fixture_view_type(monkeypatch):
    monkeypatch.setitem(registries.view_types, FIXTURE_TYPE.key, FIXTURE_TYPE)


async def _encoding(path: str) -> bytes | None:
    """The Content-Encoding a large collection body leaves `path` with."""

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b"[" + b"1," * 2000 + b"1]"})

    async def receive():
        return {"type": "http.request", "body": b""}

    messages = []

    async def send(message):
        messages.append(message)

    await CollectionCompressionMiddleware(app)(
        {"type": "http", "method": "GET", "path": path,
         "headers": [(b"accept-encoding", b"gzip")]}, receive, send
    )
    return dict(messages[0]["headers"]).get(b"content-encoding")


@pytest.mark.parametrize("path", ["/api/v1/items", "/api/v1/items/grouped", "/api/v1/fixture-rows"])
async def test_collection_compression_preserves_exact_payload_and_headers(path, fixture_view_type):
    body = b'[{"title":"A long repeated issue title"}]' * 300

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json"), (b"x-total-count", b"300")]})
        await send({"type": "http.response.body", "body": body})

    async def receive():
        return {"type": "http.request", "body": b""}

    for request_path, method, accepts in [(path, "GET", True), (path, "GET", False),
                                          (path, "POST", True), ("/api/v1/auth/me", "GET", True),
                                          ("/api/v1/attachments/file", "GET", True)]:
        messages = []

        async def send(message):
            messages.append(message)

        await CollectionCompressionMiddleware(app)(
            {"type": "http", "method": method, "path": request_path,
             "headers": [(b"accept-encoding", b"gzip")] if accepts else []}, receive, send
        )
        headers = dict(messages[0]["headers"])
        wire = b"".join(m.get("body", b"") for m in messages[1:])
        assert headers[b"x-total-count"] == b"300"
        if request_path == path and method == "GET" and accepts:
            assert headers[b"content-encoding"] == b"gzip"
            assert b"Accept-Encoding" in headers[b"vary"]
            assert gzip.decompress(wire) == body
            assert len(wire) < len(body) / 2
        else:
            assert b"content-encoding" not in headers
            assert wire == body


async def test_a_list_surfaces_rows_compress_only_while_its_plugin_is_loaded(monkeypatch):
    """The set is derived from the registry, so a disabled plugin's path leaves with
    it and the host never names an optional plugin's route."""
    assert await _encoding("/api/v1/fixture-rows") is None
    monkeypatch.setitem(registries.view_types, FIXTURE_TYPE.key, FIXTURE_TYPE)
    assert await _encoding("/api/v1/fixture-rows") == b"gzip"


async def test_the_configured_api_prefix_is_the_one_compressed(monkeypatch, fixture_view_type):
    monkeypatch.setattr(settings, "api_prefix", "/api/v9")
    assert await _encoding("/api/v9/items") == b"gzip"
    assert await _encoding("/api/v9/fixture-rows") == b"gzip"
    assert await _encoding("/api/v1/items") is None
