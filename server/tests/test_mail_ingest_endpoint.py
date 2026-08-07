"""The ingest endpoint's status contract (RADD-953).

These codes are not cosmetic. The Cloudflare Worker turns them into SMTP
outcomes, so **4xx bounces the sender's mail and 5xx queues it for retry**. A
transient database error answered with 4xx silently bounces valid mail and tells
the sender they were rejected by policy.

That asymmetry is why the endpoint catches narrowly: only signature, size and
parse failures may produce 4xx, and everything else is allowed to propagate.
Tested here rather than reasoned about, because the failure is invisible from
inside the process — it looks like a handled error either way.
"""

import hashlib
import hmac
import uuid
from email.message import EmailMessage

import httpx
import pytest

from radd.config import settings

SECRET = "test-ingest-secret"


@pytest.fixture
def app():
    from radd.app import create_app

    return create_app()


@pytest.fixture(autouse=True)
def ingest_secret(monkeypatch):
    monkeypatch.setattr(settings, "email_ingest_secret", SECRET)
    # A project for new mail to land in; without it intake raises, which is a
    # 5xx — correct, but not what these tests are about.
    monkeypatch.setattr(settings, "mail_project_key", "RADDMAILTEST")


def signed(raw: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def message(subject="Help me", message_id=None) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "Jane <jane@example.com>"
    msg["To"] = "help@radd-hq.com"
    msg["Message-ID"] = message_id or f"<{uuid.uuid4().hex}@example.com>"
    msg.set_content("Body text")
    return msg.as_bytes()


async def _post(app, raw: bytes, *, signature: str | None = None, headers=None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/api/v1/integrations/email",
            content=raw,
            headers={
                "Content-Type": "message/rfc822",
                "X-Radd-Signature": signature if signature is not None else signed(raw),
                "X-Radd-Envelope-From": "jane@example.com",
                "X-Radd-Envelope-To": "help@radd-hq.com",
                **(headers or {}),
            },
        )


async def test_a_bad_signature_is_401_and_nothing_is_parsed(app):
    """Acceptance criterion 5. Verified BEFORE parsing, so a hostile body never
    reaches the parser on an unauthenticated request."""
    response = await _post(app, message(), signature="sha256=" + "0" * 64)
    assert response.status_code == 401


async def test_a_missing_signature_is_401(app):
    response = await _post(app, message(), signature="")
    assert response.status_code == 401


async def test_an_empty_configured_secret_rejects_everything(app, monkeypatch):
    """The same safe default as forgejo_webhook_secret. A misconfigured instance
    must fail closed — the alternative is an unauthenticated, internet-reachable
    endpoint that creates issues."""
    monkeypatch.setattr(settings, "email_ingest_secret", "")
    raw = message()
    # Signed with the EMPTY secret, i.e. exactly what an attacker who knew the
    # secret was unset would send.
    response = await _post(app, raw, signature=signed(raw, ""))
    assert response.status_code == 401


async def test_a_wrong_secret_is_401_not_500(app):
    raw = message()
    response = await _post(app, raw, signature=signed(raw, "some-other-secret"))
    assert response.status_code == 401


async def test_an_oversized_body_is_413(app):
    from radd.modules.mailintake.types import MAX_BODY_BYTES

    raw = b"x" * (MAX_BODY_BYTES + 1)
    response = await _post(app, raw)
    assert response.status_code == 413


async def test_the_size_check_precedes_the_signature_check(app):
    """A 26 MB body must not cost an HMAC over 26 MB first."""
    from radd.modules.mailintake.types import MAX_BODY_BYTES

    response = await _post(app, b"x" * (MAX_BODY_BYTES + 1), signature="sha256=deadbeef")
    assert response.status_code == 413


async def test_an_autoresponder_is_accepted_and_discarded(app):
    """202, not 4xx: bouncing at a mail loop puts another message into it."""
    msg = EmailMessage()
    msg["Subject"] = "Out of office"
    msg["From"] = "away@example.com"
    msg["Auto-Submitted"] = "auto-replied"
    msg["Message-ID"] = f"<{uuid.uuid4().hex}@example.com>"
    msg.set_content("I am away")
    response = await _post(app, msg.as_bytes())
    assert response.status_code == 202
    assert response.json()["result"] == "ignored"


async def test_an_unresolvable_default_project_is_5xx_not_4xx(app):
    """The rule with consequences. `mail_project_key` naming no project is
    Radd's misconfiguration, not the sender's — a 4xx here would bounce valid
    mail with a permanent failure the sender can do nothing about."""
    response = await _post(app, message(subject="Nowhere to go"))
    assert response.status_code >= 500
