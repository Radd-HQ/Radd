"""A cookie-authenticated write must come from this instance (RADD-1547).

`SameSite=Lax` stops another SITE; a sibling subdomain is the same site, and
its requests arrived with the session cookie and were served.
"""

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from radd import origin_check
from radd.config import settings
from radd.modules.auth.types import SESSION_COOKIE_NAME

COOKIE = {"cookie": f"theme=dark; {SESSION_COOKIE_NAME}=abc"}


async def _ok(request):
    return PlainTextResponse("served")


async def _socket(websocket):
    await websocket.accept()
    await websocket.send_text("open")
    await websocket.close()


def _app():
    inner = Starlette(routes=[Route("/x", _ok, methods=["GET", "POST", "DELETE"]), WebSocketRoute("/ws", _socket)])
    return origin_check.OriginCheckMiddleware(inner)


@pytest.fixture(autouse=True)
def _base_url(monkeypatch):
    monkeypatch.setattr(settings, "app_base_url", "https://radd.example.com")
    monkeypatch.setattr(settings, "trusted_origins", "")
    monkeypatch.setattr(settings, "origin_check", True)


def test_the_middleware_names_the_real_session_cookie():
    assert origin_check._SESSION_COOKIE == SESSION_COOKIE_NAME


async def _post(headers, method="POST"):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://internal:8000") as client:
        return (await client.request(method, "/x", headers=headers)).status_code


async def test_a_write_from_a_sibling_origin_is_refused():
    assert await _post({**COOKIE, "origin": "https://git.example.com"}) == 403
    assert await _post({**COOKIE, "origin": "https://git.example.com"}, "DELETE") == 403
    assert await _post({**COOKIE, "origin": "null"}) == 403
    # The scheme is part of an origin: the same host over http is not this instance.
    assert await _post({**COOKIE, "origin": "http://radd.example.com"}) == 403
    # No Origin, but the browser says where it came from.
    assert await _post({**COOKIE, "sec-fetch-site": "same-site"}) == 403
    assert await _post({**COOKIE, "sec-fetch-site": "cross-site"}) == 403


async def test_this_instances_own_requests_are_served():
    assert await _post({**COOKIE, "origin": "https://radd.example.com"}) == 200  # app_base_url
    assert await _post({**COOKIE, "origin": "http://internal:8000"}) == 200  # the request's own host
    assert await _post({**COOKIE, "sec-fetch-site": "same-origin"}) == 200
    assert await _post({**COOKIE}) == 200  # curl, a script: not a browser being steered


async def test_what_the_rule_does_not_apply_to():
    foreign = {"origin": "https://git.example.com"}
    assert await _post({**COOKIE, **foreign}, "GET") == 200  # reads change nothing
    assert await _post({**foreign}) == 200  # no session cookie: nothing to ride on
    assert await _post({**COOKIE, **foreign, "authorization": "Bearer t"}) == 200  # a token is deliberate
    assert await _post({"cookie": f"not_{SESSION_COOKIE_NAME}=abc", **foreign}) == 200


async def test_a_listed_origin_is_trusted_and_the_check_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(settings, "trusted_origins", "https://portal.example.com , https://other.example.com")
    assert await _post({**COOKIE, "origin": "https://portal.example.com"}) == 200
    assert await _post({**COOKIE, "origin": "https://git.example.com"}) == 403
    monkeypatch.setattr(settings, "origin_check", False)
    assert await _post({**COOKIE, "origin": "https://git.example.com"}) == 200


def test_a_websocket_handshake_from_another_origin_is_refused():
    client = TestClient(_app(), base_url="http://internal:8000")
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/ws", headers={**COOKIE, "origin": "https://git.example.com"}):
            pass
    assert refused.value.code == 1008
    with client.websocket_connect("/ws", headers={**COOKIE, "origin": "https://radd.example.com"}) as socket:
        assert socket.receive_text() == "open"


async def test_the_real_app_has_it_installed():
    from radd.app import create_app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as client:
        refused = await client.post("/api/v1/items", json={}, headers={**COOKIE, "origin": "https://git.example.com"})
    assert refused.status_code == 403 and "RADD_TRUSTED_ORIGINS" in refused.json()["detail"]
