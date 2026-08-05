"""CommitBeforeSendMiddleware (RADD-877): API responses buffer until the app —
including the get_session commit in teardown — finishes; event streams and file
deliveries pass through incrementally instead of accumulating in RAM (a multi-GB
backup download used to be held fully in a Python list before the first byte)."""

from radd.middleware import CommitBeforeSendMiddleware


async def _drive(headers: list[tuple[bytes, bytes]]) -> tuple[int, int]:
    """Run the middleware around a fake app that sends start + two body chunks.
    Returns (messages already sent when the app returned, total sent)."""
    sent: list = []
    flushed_during_app = -1

    async def outer_send(message):
        sent.append(message)

    async def fake_app(scope, receive, send):
        nonlocal flushed_during_app
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b"a" * 8, "more_body": True})
        await send({"type": "http.response.body", "body": b"b" * 8})
        flushed_during_app = len(sent)

    mw = CommitBeforeSendMiddleware(fake_app)
    await mw({"type": "http", "method": "GET", "path": "/x"}, None, outer_send)
    return flushed_during_app, len(sent)


async def test_json_buffers_until_app_finishes():
    during, total = await _drive([(b"content-type", b"application/json")])
    assert during == 0  # nothing left before teardown ran
    assert total == 3


async def test_file_delivery_streams_immediately():
    during, total = await _drive(
        [
            (b"content-type", b"application/octet-stream"),
            (b"content-disposition", b'attachment; filename="db.dump"'),
        ]
    )
    assert during == 3  # every message left while the app was still running
    assert total == 3


async def test_inline_attachment_streams_immediately():
    # The attachment proxy serves images inline — still a file delivery.
    during, total = await _drive(
        [
            (b"content-type", b"image/png"),
            (b"content-disposition", b'inline; filename="shot.png"'),
        ]
    )
    assert during == 3
    assert total == 3


async def test_event_stream_streams_immediately():
    during, total = await _drive([(b"content-type", b"text/event-stream")])
    assert during == 3
    assert total == 3
