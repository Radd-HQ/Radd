"""Security response headers and the Secure-cookie guard (RADD-1531)."""

import base64
import hashlib

import pytest
from httpx import ASGITransport, AsyncClient

from radd import security_headers
from radd.app import create_app
from radd.config import settings
from radd.security_headers import CspMode, inline_script_hashes


@pytest.fixture
async def http():
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as client:
        yield client


async def test_every_response_carries_the_baseline(http, monkeypatch):
    monkeypatch.setattr(settings, "app_base_url", "http://localhost:8000")
    monkeypatch.setattr(settings, "csp_mode", CspMode.REPORT.value)
    for path in ("/health", f"{settings.api_prefix}/auth/me", "/no/such/page"):
        headers = (await http.get(path)).headers
        assert headers["x-content-type-options"] == "nosniff", path
        assert headers["referrer-policy"] == "strict-origin-when-cross-origin", path
        assert headers["x-frame-options"] == "DENY", path
        assert headers["content-security-policy"] == "frame-ancestors 'none'", path
        assert "script-src 'self'" in headers["content-security-policy-report-only"], path
        assert "strict-transport-security" not in headers, "HSTS on a deployment that is not https"


async def test_hsts_only_when_the_deployment_says_it_is_https(http, monkeypatch):
    monkeypatch.setattr(settings, "app_base_url", "https://radd.example.com")
    assert (await http.get("/health")).headers["strict-transport-security"].startswith("max-age=")


async def test_enforce_is_one_policy_that_includes_framing_and_off_removes_the_csp(http, monkeypatch):
    monkeypatch.setattr(settings, "csp_mode", CspMode.ENFORCE.value)
    headers = (await http.get("/health")).headers
    assert "content-security-policy-report-only" not in headers
    assert "script-src 'self'" in headers["content-security-policy"]
    assert headers["content-security-policy"].endswith("frame-ancestors 'none'")

    monkeypatch.setattr(settings, "csp_mode", CspMode.OFF.value)
    headers = (await http.get("/health")).headers
    assert "content-security-policy-report-only" not in headers
    assert headers["content-security-policy"] == "frame-ancestors 'none'", "framing must stay protected"


async def test_an_operator_can_allow_a_frame_ancestor(http, monkeypatch):
    monkeypatch.setattr(settings, "frame_ancestors", "https://intranet.example.com")
    headers = (await http.get("/health")).headers
    assert headers["content-security-policy"] == "frame-ancestors https://intranet.example.com"
    assert "x-frame-options" not in headers, "DENY would contradict the allowed ancestor"


def test_the_shell_inline_script_is_allowed_by_hash_not_by_unsafe_inline(tmp_path, monkeypatch):
    body = b'{"imports": {"react": "/shared/react.js"}}'
    shell = b'<html><head><script type="importmap">' + body + b'</script></head>' \
            b'<body><script type="module" src="/assets/index-abc.js"></script></body></html>'
    expected = "'sha256-" + base64.b64encode(hashlib.sha256(body).digest()).decode() + "'"
    assert inline_script_hashes(shell) == (expected,), "a script WITH src must not be hashed"

    (tmp_path / "index.html").write_bytes(shell)
    monkeypatch.setattr(settings, "web_dist", str(tmp_path))
    monkeypatch.setattr(security_headers, "_shell_hashes", None)
    policy = security_headers.content_security_policy()
    assert f"script-src 'self' {expected};" in policy
    assert "'unsafe-inline'" not in policy.split("script-src")[1].split(";")[0]


def test_the_session_cookie_is_secure_whenever_the_deployment_is_https(monkeypatch):
    """A forgotten RADD_SESSION_COOKIE_SECURE must not send the session in clear."""
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    monkeypatch.setattr(settings, "app_base_url", "https://radd.example.com")
    assert settings.effective_cookie_secure is True
    monkeypatch.setattr(settings, "app_base_url", "http://localhost:8000")
    assert settings.effective_cookie_secure is False  # local http still works
    monkeypatch.setattr(settings, "session_cookie_secure", True)
    assert settings.effective_cookie_secure is True
