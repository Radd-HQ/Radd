"""Where a user-supplied URL may make the server call (RADD-1546).

Webhook endpoints and automation HTTP actions used to call whatever URL they
were given. These pin the guard: what is refused on its face at save, what is
refused once the name is resolved, that the request goes to the address that
was checked, and that an operator's allow-list opens exactly what it names.
"""

import socket

import httpx
import pytest

from radd import outbound
from radd.config import settings
from radd.modules.automations.builtin_actions import _check
from radd.modules.automations.types import ActionType
from radd.modules.webhooks.schemas import EndpointCreate, EndpointUpdate

REFUSED_ON_SIGHT = [
    "http://127.0.0.1/hook",
    "http://127.0.0.1:5432/",
    "http://localhost:8000/x",
    "http://api.localhost/x",
    "http://10.0.0.5/hook",
    "http://172.16.4.4/hook",
    "http://192.168.1.10/hook",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
    "http://100.64.0.1/x",  # carrier-grade NAT
    "http://0.0.0.0/x",
    "http://[::1]/x",
    "http://[fd00::1]/x",  # unique-local
    "http://[fe80::1]/x",  # link-local
    "http://[::ffff:127.0.0.1]/x",  # IPv4 loopback in an IPv6 coat
    "http://user:secret@example.com/x",
    "ftp://example.com/x",
    "http:///nohost",
]


@pytest.mark.parametrize("url", REFUSED_ON_SIGHT)
def test_refused_at_save(url):
    with pytest.raises(outbound.OutboundRefused):
        outbound.check_url(url)


@pytest.mark.parametrize("url", ["https://example.com/hook", "http://93.184.216.34:8080/x", "https://[2606:2800:220:1::1]/x"])
def test_public_urls_pass_the_save_check(url):
    outbound.check_url(url)


def test_the_webhook_and_automation_forms_refuse_what_the_guard_refuses():
    with pytest.raises(ValueError, match="not a public address"):
        EndpointCreate(url="http://169.254.169.254/latest/meta-data/")
    with pytest.raises(ValueError, match="not a public address"):
        EndpointUpdate(url="http://10.1.2.3/x")
    assert EndpointUpdate(description="unchanged url").url is None
    assert EndpointCreate(url="https://example.com/hook").url == "https://example.com/hook"
    with pytest.raises(ValueError, match="not a public address"):
        _check(ActionType.SEND_WEBHOOK)({"url": "http://127.0.0.1:9000/x"})
    with pytest.raises(ValueError, match="not a public address"):
        _check(ActionType.POST_CHAT)({"webhook_url": "http://192.168.0.2/chat", "message": "hi"})
    _check(ActionType.POST_CHAT)({"webhook_url": "https://chat.example.com/hook", "message": "hi"})


def _resolver(monkeypatch, answers: dict[str, list[str]]):
    async def fake(self, host, port, **_kwargs):
        if host not in answers:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in answers[host]]

    import asyncio

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake)


async def test_a_name_that_resolves_to_a_private_address_is_refused_at_send(monkeypatch):
    """The save check cannot see this: the name is public-looking, its answer is not."""
    _resolver(monkeypatch, {"innocent.example": ["10.9.8.7"], "mixed.example": ["93.184.216.34", "127.0.0.1"]})
    with pytest.raises(outbound.OutboundRefused, match="10.9.8.7"):
        await outbound.resolve("https://innocent.example/hook")
    # ONE private answer among public ones is enough: the connection could land on it.
    with pytest.raises(outbound.OutboundRefused, match="127.0.0.1"):
        await outbound.resolve("https://mixed.example/hook")
    with pytest.raises(outbound.OutboundRefused, match="does not resolve"):
        await outbound.resolve("https://nowhere.example/hook")


async def test_the_request_goes_to_the_address_that_was_checked(monkeypatch):
    """No second lookup: the request is addressed to the vetted IP, and carries
    the name only as Host and as the TLS server name."""
    _resolver(monkeypatch, {"hooks.example": ["93.184.216.34"]})
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(url=str(request.url), host=request.headers["host"], sni=request.extensions.get("sni_hostname"),
                    body=request.content, signature=request.headers.get("x-signature"))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/steal"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await outbound.post(
            client, "https://hooks.example:8443/in?x=1", content=b"{}", headers={"x-signature": "abc"}
        )
    assert seen == {
        "url": "https://93.184.216.34:8443/in?x=1", "host": "hooks.example:8443",
        "sni": "hooks.example", "body": b"{}", "signature": "abc",
    }
    # A redirect is an answer, not an instruction: it is returned, never followed.
    assert response.status_code == 302


async def test_an_operator_can_allow_an_internal_target_and_only_that(monkeypatch):
    _resolver(monkeypatch, {"chat.internal.example": ["10.20.3.4"], "db.internal.example": ["10.99.0.1"]})
    monkeypatch.setattr(settings, "outbound_allowed_hosts", "chat.internal.example, 10.20.0.0/16")
    assert (await outbound.resolve("http://chat.internal.example/hook"))[3].compressed == "10.20.3.4"
    outbound.check_url("http://10.20.3.4/hook")  # inside the allowed range
    with pytest.raises(outbound.OutboundRefused):
        outbound.check_url("http://10.99.0.1/hook")
    with pytest.raises(outbound.OutboundRefused):
        await outbound.resolve("http://db.internal.example/x")
    # Link-local stays closed unless it is itself listed.
    with pytest.raises(outbound.OutboundRefused):
        outbound.check_url("http://169.254.169.254/")
