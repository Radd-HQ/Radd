"""What the server compresses, and what it deliberately leaves alone (RADD-1549)."""

import gzip

import pytest

from radd import compression
from radd.compression import CompressionMiddleware
from radd.config import settings

BODY = b'[{"title":"A long repeated issue title"}]' * 300


async def _get(path, *, method="GET", accepts=True, content_type=b"application/json", body=BODY,
               extra=(), chunks=1, status=200, calls=None):
    async def app(scope, receive, send):
        if calls is not None:
            calls.append(path)
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", content_type), (b"x-total-count", b"300"), *extra]})
        size = max(1, len(body) // chunks)
        parts = [body[i:i + size] for i in range(0, len(body), size)] or [b""]
        for index, part in enumerate(parts):
            await send({"type": "http.response.body", "body": part, "more_body": index < len(parts) - 1})

    async def receive():
        return {"type": "http.request", "body": b""}

    messages = []

    async def send(message):
        messages.append(message)

    await CompressionMiddleware(app)(
        {"type": "http", "method": method, "path": path,
         "headers": [(b"accept-encoding", b"gzip, br")] if accepts else []}, receive, send
    )
    headers = dict(messages[0]["headers"])
    return headers, b"".join(m.get("body", b"") for m in messages[1:])


@pytest.fixture(autouse=True)
def _empty_asset_cache():
    compression.assets.entries.clear()
    compression.assets.size = 0


@pytest.mark.parametrize("path", ["/api/v1/items", "/api/v1/labels", "/api/v1/fields", "/plugins/x/remoteEntry.js", "/"])
async def test_a_text_response_is_compressed_and_arrives_intact(path):
    headers, wire = await _get(path)
    assert headers[b"content-encoding"] == b"gzip"
    assert b"Accept-Encoding" in headers[b"vary"]
    assert headers[b"x-total-count"] == b"300"  # the response's own headers survive
    assert b"content-length" not in headers
    assert gzip.decompress(wire) == BODY and len(wire) < len(BODY) / 2


async def test_a_streamed_body_is_one_valid_gzip_stream():
    headers, wire = await _get("/api/v1/items", chunks=7)
    assert headers[b"content-encoding"] == b"gzip" and gzip.decompress(wire) == BODY


@pytest.mark.parametrize(
    "kwargs",
    [
        {"accepts": False},  # the client did not ask
        {"method": "POST"},  # only reads
        {"body": b'{"ok":true}'},  # too small to be worth it
        {"content_type": b"image/png"},  # already compressed formats
        {"content_type": b"application/octet-stream"},
        {"content_type": b"text/event-stream"},  # a stream must not be held back
        {"extra": ((b"content-encoding", b"br"),)},  # a proxy or the app already did
        {"status": 404},
    ],
)
async def test_what_is_left_alone(kwargs):
    headers, wire = await _get("/api/v1/items", **kwargs)
    assert headers.get(b"content-encoding") in (None, b"br")
    assert wire == kwargs.get("body", BODY)


@pytest.mark.parametrize("path", ["/api/v1/auth/me", "/api/v1/auth/me/preferences", "/api/v1/tokens",
                                  "/api/v1/attachments/file", "/api/v1/backups/1/download"])
async def test_routes_that_are_never_compressed(path):
    headers, wire = await _get(path)
    assert b"content-encoding" not in headers and wire == BODY


async def test_the_exclusions_follow_the_configured_api_prefix(monkeypatch):
    monkeypatch.setattr(settings, "api_prefix", "/api/v9")
    assert b"content-encoding" not in (await _get("/api/v9/auth/me"))[0]
    # Under another prefix that path is just a path.
    assert (await _get("/api/v1/auth/me"))[0][b"content-encoding"] == b"gzip"


async def test_an_immutable_asset_is_compressed_once_and_then_served_from_memory():
    immutable = ((b"cache-control", b"public, max-age=31536000, immutable"), (b"etag", b'"abc"'))
    calls = []
    script = b"export const x = 1;\n" * 2000
    first, wire = await _get("/assets/index-abc.js", content_type=b"text/javascript", body=script,
                             extra=immutable, chunks=5, calls=calls)
    assert gzip.decompress(wire) == script
    # Sent whole, so the browser knows its length; and the caching headers are intact.
    assert int(first[b"content-length"]) == len(wire) and first[b"etag"] == b'"abc"'
    again, wire_again = await _get("/assets/index-abc.js", content_type=b"text/javascript", body=script,
                                   extra=immutable, calls=calls)
    assert calls == ["/assets/index-abc.js"], "the second request reached the file again"
    assert wire_again == wire and again[b"content-encoding"] == b"gzip"
    # A client that does not accept gzip still gets the plain file.
    plain, body = await _get("/assets/index-abc.js", content_type=b"text/javascript", body=script,
                             extra=immutable, accepts=False, calls=calls)
    assert b"content-encoding" not in plain and body == script
    # A revalidated (not immutable) file is compressed but never cached.
    await _get("/assets/other.js", content_type=b"text/javascript", body=script, calls=calls)
    assert "/assets/other.js" not in compression.assets.entries


async def test_the_asset_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(compression, "ASSET_CACHE_BYTES", 400)
    for name in ("a", "b", "c", "d"):
        compression.assets.put(f"/assets/{name}.js", [], b"x" * 90)
        compression.assets.put(f"/assets/{name}.js", [], b"x" * 90)  # twice: counted once
    compression.assets.put("/assets/e.js", [], b"x" * 90)
    assert compression.assets.size <= 400 and "/assets/a.js" not in compression.assets.entries
