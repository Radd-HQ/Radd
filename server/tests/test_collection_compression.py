import gzip

import pytest

from radd.collection_compression import CollectionCompressionMiddleware


@pytest.mark.parametrize("path", ["/api/v1/items", "/api/v1/items/grouped", "/api/v1/sla-queue-items"])
async def test_collection_compression_preserves_exact_payload_and_headers(path):
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
