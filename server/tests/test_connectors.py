"""Connector wave core (spec 47): forgejo, googlechat, alertmanager, mailintake.

Pure tests of the pieces correctness hangs on — webhook payload → plan parsing,
message formatting, alert dedup planning, raw-email parsing — plus the forgejo
HMAC check and the alertmanager token check over in-process ASGI apps with the
service layer mocked (the alert_items migration is applied by the supervisor,
and there is no IMAP server in CI; live flows are verified separately)."""

import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from radd.config import settings
from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.alertmanager import planner, service as alert_service
from radd.modules.alertmanager.router import router as alertmanager_router
from radd.modules.alertmanager.types import AlertAction
from radd.modules.forgejo import parsing as forgejo_parsing, service as forgejo_service
from radd.modules.forgejo.router import router as forgejo_router, verify_signature
from radd.modules.googlechat.formatter import format_message
from radd.modules.mailintake.parsing import extract_reply_key, parse_email
from radd.modules.mailintake.types import BODY_MAX_CHARS
from radd.modules.vcs.types import VcsRefType

# --- forgejo: key extraction + push/pull_request planning (pure) ---


def test_forgejo_extract_keys_bounded_cased_deduped():
    assert forgejo_parsing.extract_keys("td-12 fixes TD-12 and DEV-3, sha1-2abc") == [
        "TD-12",
        "DEV-3",
    ]
    assert forgejo_parsing.extract_keys("feature/td-99-fix-farm") == ["TD-99"]
    assert forgejo_parsing.extract_keys(None, "", "no keys here") == []


# Realistic Forgejo push webhook payload (abridged to the fields the parser reads).
FORGEJO_PUSH = {
    "ref": "refs/heads/td-7-farm-fix",
    "before": "0000000000000000000000000000000000000000",
    "after": "4b2b1cdeadbeef1122334455667788990011aabb",
    "compare_url": "https://forge.example.com/pipe/tools/compare/000...4b2",
    "commits": [
        {
            "id": "4b2b1cdeadbeef1122334455667788990011aabb",
            "message": "TD-7: restart render daemon\n\nlong body\n",
            "url": "https://forge.example.com/pipe/tools/commit/4b2b1cde",
            "author": {"name": "Jane", "email": "jane@example.com", "username": "jane"},
            "timestamp": "2026-07-20T10:00:00Z",
        },
        {
            "id": "aaaa000011112222333344445555666677778888",
            "message": "unrelated cleanup\n",
            "url": "https://forge.example.com/pipe/tools/commit/aaaa0000",
            "author": {"name": "Jane", "email": "jane@example.com", "username": "jane"},
            "timestamp": "2026-07-20T10:05:00Z",
        },
    ],
    "total_commits": 2,
    "repository": {
        "id": 5,
        "name": "tools",
        "full_name": "pipe/tools",
        "html_url": "https://forge.example.com/pipe/tools",
    },
    "pusher": {"login": "jane"},
    "sender": {"login": "jane"},
}


def test_forgejo_plan_push_links_branch_and_commits():
    planned = forgejo_parsing.plan_push(FORGEJO_PUSH)
    assert [(p.item_key, p.ref_type) for p in planned] == [
        ("TD-7", VcsRefType.BRANCH),
        ("TD-7", VcsRefType.COMMIT),
    ]
    branch, commit = planned
    assert branch.external_id == "branch:pipe/tools:td-7-farm-fix"
    assert branch.url == "https://forge.example.com/pipe/tools/src/branch/td-7-farm-fix"
    assert commit.title == "TD-7: restart render daemon"
    assert commit.external_id == "4b2b1cdeadbeef1122334455667788990011aabb"


def _forgejo_pr_payload(*, state: str, merged: bool, action: str) -> dict:
    """Realistic Forgejo pull_request webhook payload (abridged)."""
    return {
        "action": action,
        "number": 12,
        "pull_request": {
            "id": 44,
            "number": 12,
            "title": "Fix render farm (TD-7)",
            "body": "Also touches DEV-3.",
            "state": state,
            "merged": merged,
            "html_url": "https://forge.example.com/pipe/tools/pulls/12",
            "head": {"ref": "td-7-farm-fix", "sha": "4b2b1cde"},
            "base": {"ref": "main"},
        },
        "repository": {"full_name": "pipe/tools", "html_url": "https://forge.example.com/pipe/tools"},
        "sender": {"login": "jane"},
    }


def test_forgejo_plan_pull_request_open():
    links, merged = forgejo_parsing.plan_pull_request(
        _forgejo_pr_payload(state="open", merged=False, action="opened")
    )
    assert merged is False
    assert [link.item_key for link in links] == ["TD-7", "DEV-3"]
    assert all(link.ref_type is VcsRefType.MERGE_REQUEST for link in links)
    assert links[0].external_id == "pr:pipe/tools:12"
    assert links[0].status == "open"


def test_forgejo_plan_pull_request_merged():
    links, merged = forgejo_parsing.plan_pull_request(
        _forgejo_pr_payload(state="closed", merged=True, action="closed")
    )
    assert merged is True
    assert links[0].status == "merged"


def test_forgejo_plan_pull_request_closed_unmerged():
    links, merged = forgejo_parsing.plan_pull_request(
        _forgejo_pr_payload(state="closed", merged=False, action="closed")
    )
    assert merged is False
    assert links[0].status == "closed"


# --- forgejo: HMAC signature check ---


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_forgejo_verify_signature_constant_time_hex():
    body = b'{"ref": "refs/heads/main"}'
    assert verify_signature(body, _sign(body, "s3cret"), "s3cret") is True
    assert verify_signature(body, _sign(body, "wrong"), "s3cret") is False
    assert verify_signature(body, "", "s3cret") is False


def _connector_app() -> FastAPI:
    """Minimal in-process app: just the connector routers + the 403 handler,
    with the DB session dependency stubbed out (no writes in these tests)."""
    app = FastAPI()

    @app.exception_handler(ForbiddenError)
    async def forbidden(request: Request, exc: ForbiddenError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    async def fake_session():
        yield None

    app.dependency_overrides[get_session] = fake_session
    app.include_router(forgejo_router, prefix=settings.api_prefix)
    app.include_router(alertmanager_router, prefix=settings.api_prefix)
    return app


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_connector_app()), base_url="http://test"
    )


def _connections(monkeypatch, *secrets: str, active: bool = True) -> None:
    """Spec 111: the receiver takes its secret from a CONNECTION row, so a test
    that used to set `settings.forgejo_webhook_secret` stubs the row list. The
    payloads here carry no repository name, so resolution falls through to the
    active-connection scan — which is the path being exercised."""
    rows = [
        SimpleNamespace(id=index, name=f"c{index}", webhook_secret=secret, active=active)
        for index, secret in enumerate(secrets)
    ]

    async def fake_list(session):
        return rows

    monkeypatch.setattr(forgejo_service, "list_connections", fake_list)


# A push referencing no item keys: the endpoint accepts it without touching the DB.
KEYLESS_PUSH = json.dumps({"ref": "refs/heads/main", "commits": [], "repository": {}}).encode()


async def test_forgejo_endpoint_refuses_when_no_connection_verifies(monkeypatch):
    _connections(monkeypatch)  # no rows at all — the connector is not configured
    async with _client() as client:
        response = await client.post(
            f"{settings.api_prefix}/integrations/forgejo",
            content=KEYLESS_PUSH,
            headers={"X-Forgejo-Signature": _sign(KEYLESS_PUSH, "anything")},
        )
    assert response.status_code == 403


async def test_forgejo_endpoint_rejects_bad_signature(monkeypatch):
    _connections(monkeypatch, "s3cret")
    async with _client() as client:
        response = await client.post(
            f"{settings.api_prefix}/integrations/forgejo",
            content=KEYLESS_PUSH,
            headers={
                "X-Forgejo-Signature": _sign(KEYLESS_PUSH, "wrong"),
                "X-Forgejo-Event": "push",
            },
        )
    assert response.status_code == 403


@pytest.mark.parametrize("header", ["X-Forgejo-Signature", "X-Gitea-Signature"])
async def test_forgejo_endpoint_accepts_either_signature_header(monkeypatch, header):
    _connections(monkeypatch, "s3cret")
    async with _client() as client:
        response = await client.post(
            f"{settings.api_prefix}/integrations/forgejo",
            content=KEYLESS_PUSH,
            headers={header: _sign(KEYLESS_PUSH, "s3cret"), "X-Forgejo-Event": "push"},
        )
    assert response.status_code == 200
    assert response.json() == {"linked": 0, "transitioned": 0}


async def test_forgejo_endpoint_ignores_unhandled_event_kinds(monkeypatch):
    _connections(monkeypatch, "s3cret")
    body = json.dumps({"anything": True}).encode()
    async with _client() as client:
        response = await client.post(
            f"{settings.api_prefix}/integrations/forgejo",
            content=body,
            headers={"X-Gitea-Signature": _sign(body, "s3cret"), "X-Gitea-Event": "issues"},
        )
    assert response.status_code == 200
    assert response.json() == {"linked": 0, "transitioned": 0}


# --- googlechat: pure message formatting ---

SELECTED = frozenset({"item.created", "sla.breached", "doc_page.created"})


def _event(event_type: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(event_type=event_type, payload=payload)


def test_googlechat_formats_item_created():
    text = format_message(
        _event("item.created", {"key": "TD-12", "title": "Farm down"}),
        selected=SELECTED,
        base_url="https://radd.example.com",
    )
    assert text == "New item TD-12: Farm down\nhttps://radd.example.com/issues/TD-12"


def test_googlechat_formats_sla_breached():
    text = format_message(
        _event(
            "sla.breached",
            {"item_key": "TD-12", "policy_name": "Support", "kind": "response"},
        ),
        selected=SELECTED,
        base_url="https://radd.example.com",
    )
    assert text is not None
    assert "SLA breached (response) on TD-12" in text
    assert "https://radd.example.com/issues/TD-12" in text


def test_googlechat_formats_doc_page_created():
    text = format_message(
        _event("doc_page.created", {"title": "Render farm runbook"}),
        selected=SELECTED,
        base_url="https://radd.example.com",
    )
    assert text == "New doc page: Render farm runbook\nhttps://radd.example.com"


def test_googlechat_returns_none_for_unselected_or_unknown():
    # A type outside the selected set is never posted, even if formattable.
    assert (
        format_message(
            _event("item.created", {"key": "TD-1", "title": "x"}),
            selected=frozenset({"sla.breached"}),
            base_url="https://radd.example.com",
        )
        is None
    )
    # A selected type with no formatter (or unusable payload) is skipped too.
    assert (
        format_message(
            _event("comment.created", {}),
            selected=frozenset({"comment.created"}),
            base_url="https://radd.example.com",
        )
        is None
    )
    assert (
        format_message(_event("item.created", {}), selected=SELECTED, base_url="https://x")
        is None
    )


# --- alertmanager: pure alert planning (firing new / dup / resolved) ---


def _alert(status: str, fingerprint: str, **overrides) -> dict:
    alert = {
        "status": status,
        "labels": {"alertname": "HighCPU", "instance": "farm-03"},
        "annotations": {"summary": "CPU above 95% for 10m", "description": "node hot"},
        "startsAt": "2026-07-20T09:00:00Z",
        "endsAt": "0001-01-01T00:00:00Z",
        "generatorURL": "https://prom.example.com/graph?g0.expr=cpu",
        "fingerprint": fingerprint,
    }
    alert.update(overrides)
    return alert


def test_alertmanager_plans_create_for_new_firing_fingerprint():
    plans = planner.plan_alerts({"status": "firing", "alerts": [_alert("firing", "fp1")]})
    assert len(plans) == 1
    plan = plans[0]
    assert plan.action is AlertAction.CREATE
    assert plan.fingerprint == "fp1"
    assert plan.title == "HighCPU: CPU above 95% for 10m"
    assert "| alertname (label) | HighCPU |" in plan.description
    assert "| summary (annotation) | CPU above 95% for 10m |" in plan.description
    assert "https://prom.example.com/graph?g0.expr=cpu" in plan.description


def test_alertmanager_plans_comment_for_known_firing_fingerprint():
    plans = planner.plan_alerts(
        {"alerts": [_alert("firing", "fp1"), _alert("firing", "fp2")]},
        existing=frozenset({"fp1"}),
    )
    assert [(p.action, p.fingerprint) for p in plans] == [
        (AlertAction.STILL_FIRING, "fp1"),
        (AlertAction.CREATE, "fp2"),
    ]
    assert "2 firing alert(s)" in plans[0].comment


def test_alertmanager_plans_resolved_only_for_known_fingerprints():
    plans = planner.plan_alerts(
        {"alerts": [_alert("resolved", "fp1"), _alert("resolved", "fp-unknown")]},
        existing=frozenset({"fp1"}),
    )
    assert [(p.action, p.fingerprint) for p in plans] == [(AlertAction.RESOLVED, "fp1")]
    assert plans[0].comment


def test_alertmanager_skips_alerts_without_fingerprint_and_dedupes_in_batch():
    plans = planner.plan_alerts(
        {"alerts": [_alert("firing", ""), _alert("firing", "fp1"), _alert("firing", "fp1")]}
    )
    # No fingerprint = skipped; a repeat in the same payload is a dup, not a 2nd item.
    assert [p.action for p in plans] == [AlertAction.CREATE, AlertAction.STILL_FIRING]


# --- alertmanager: endpoint token check (service layer mocked — the alert_items
# migration is applied by the supervisor, so no DB writes here) ---

AM_PAYLOAD = {"version": "4", "status": "firing", "alerts": []}


async def test_alertmanager_endpoint_disabled_without_token(monkeypatch):
    monkeypatch.setattr(settings, "alertmanager_token", "")
    async with _client() as client:
        response = await client.post(
            f"{settings.api_prefix}/integrations/alertmanager?token=whatever", json=AM_PAYLOAD
        )
    assert response.status_code == 403


async def test_alertmanager_endpoint_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(settings, "alertmanager_token", "t0ken")
    async with _client() as client:
        response = await client.post(
            f"{settings.api_prefix}/integrations/alertmanager?token=nope", json=AM_PAYLOAD
        )
    assert response.status_code == 403


async def test_alertmanager_endpoint_accepts_query_token_and_bearer(monkeypatch):
    monkeypatch.setattr(settings, "alertmanager_token", "t0ken")

    async def fake_process(session, payload):
        assert payload == AM_PAYLOAD
        return {"created": 1, "commented": 0, "transitioned": 0}

    monkeypatch.setattr(alert_service, "process", fake_process)
    async with _client() as client:
        by_query = await client.post(
            f"{settings.api_prefix}/integrations/alertmanager?token=t0ken", json=AM_PAYLOAD
        )
        by_bearer = await client.post(
            f"{settings.api_prefix}/integrations/alertmanager",
            json=AM_PAYLOAD,
            headers={"Authorization": "Bearer t0ken"},
        )
    assert by_query.status_code == 200
    assert by_query.json() == {"created": 1, "commented": 0, "transitioned": 0}
    assert by_bearer.status_code == 200


# --- mailintake: pure raw-email parsing (fixture bytes) ---

SIMPLE_EMAIL = (
    b"From: Jane Doe <Jane@Example.com>\r\n"
    b"To: support@example.com\r\n"
    b"Subject: Printer on fire\r\n"
    b"MIME-Version: 1.0\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"The printer in room 3 is on fire.\r\n"
)

MULTIPART_REPLY = (
    b"From: bob@example.com\r\n"
    b"Subject: Re: [TD-123] Printer on fire\r\n"
    b"MIME-Version: 1.0\r\n"
    b'Content-Type: multipart/alternative; boundary="XYZ"\r\n'
    b"\r\n"
    b"--XYZ\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"Still burning.\r\n"
    b"--XYZ\r\n"
    b"Content-Type: text/html; charset=utf-8\r\n"
    b"\r\n"
    b"<p>Still burning.</p>\r\n"
    b"--XYZ--\r\n"
)


def test_mail_parse_simple_text_email():
    plan = parse_email(SIMPLE_EMAIL)
    assert plan.subject == "Printer on fire"
    assert plan.sender_name == "Jane Doe"
    assert plan.sender_email == "jane@example.com"  # lower-cased for user matching
    assert plan.body == "The printer in room 3 is on fire."
    assert plan.item_key is None  # bare subject = new item, not a reply


def test_mail_parse_multipart_prefers_plain_and_threads_by_bracketed_key():
    plan = parse_email(MULTIPART_REPLY)
    assert plan.body == "Still burning."
    assert plan.item_key == "TD-123"
    assert plan.sender_email == "bob@example.com"


def test_mail_subject_key_extraction_rules():
    assert extract_reply_key("[TD-123] Printer on fire") == "TD-123"
    assert extract_reply_key("Re: TD-45 broken again") == "TD-45"
    assert extract_reply_key("RE: re: TD-45 broken again") == "TD-45"
    assert extract_reply_key("Fwd: dev-3 escalation") == "DEV-3"
    # A bare key without a reply prefix or brackets files a NEW item.
    assert extract_reply_key("TD-9 broken") is None
    assert extract_reply_key("Re: no key here") is None
    assert extract_reply_key("") is None


def test_mail_body_truncated_to_limit():
    long_body = b"x" * (BODY_MAX_CHARS + 500)
    raw = (
        b"From: a@b.co\r\nSubject: big\r\nContent-Type: text/plain\r\n\r\n" + long_body + b"\r\n"
    )
    plan = parse_email(raw)
    assert len(plan.body) == BODY_MAX_CHARS


def test_mail_parse_tolerates_missing_headers_and_body():
    plan = parse_email(b"\r\n")
    assert plan.subject == ""
    assert plan.sender_email == ""
    assert plan.body == ""
    assert plan.item_key is None


# --- mailintake: plus-address project routing + Message-ID capture (spec 62) ---


def _mail(headers: dict[str, str], body: str = "help") -> bytes:
    lines = "".join(f"{key}: {value}\r\n" for key, value in headers.items())
    return (lines + "Content-Type: text/plain\r\n\r\n" + body + "\r\n").encode()


def test_mail_plus_address_routes_by_project_key():
    plan = parse_email(_mail({"From": "a@b.co", "Subject": "x", "To": "support+td@example.com"}))
    assert plan.project_key == "TD"  # case-insensitive, upper-cased


def test_mail_plus_address_checks_headers_in_priority_order():
    plan = parse_email(
        _mail(
            {
                "From": "a@b.co",
                "Subject": "x",
                "To": "Support Desk <support@example.com>",
                "Cc": "helpdesk+dev3@example.com",
                "X-Original-To": "support+td@example.com",
            }
        )
    )
    assert plan.project_key == "DEV3"  # Cc beats the later X-Original-To


def test_mail_plus_address_ignores_non_key_tags_and_plain_recipients():
    # A tag that can't be a project key (leading digit / too long) is no route.
    assert parse_email(_mail({"To": "support+123@example.com"})).project_key is None
    assert parse_email(_mail({"To": "support+waytoolongkey99@example.com"})).project_key is None
    assert parse_email(_mail({"To": "support@example.com"})).project_key is None
    assert parse_email(b"\r\n").project_key is None


def test_mail_plus_address_takes_the_last_plus_segment():
    plan = parse_email(_mail({"Delivered-To": "in+box+TD@example.com"}))
    assert plan.project_key == "TD"


def test_mail_message_id_captured_verbatim():
    plan = parse_email(
        _mail({"From": "a@b.co", "Subject": "x", "Message-ID": "<abc-123@mail.example>"})
    )
    assert plan.message_id == "<abc-123@mail.example>"
    assert parse_email(b"\r\n").message_id == ""


# --- mailintake: outbound reply decision (pure, spec 62) ---


def test_should_reply_happy_path_and_full_refusal_matrix():
    import uuid

    from radd.modules.automations.types import SYSTEM_ACTOR_ID
    from radd.modules.mailintake.outbound import should_reply

    agent = uuid.uuid4()
    ok = dict(has_contact=True, visibility="public", actor_id=agent)
    assert should_reply(**ok) is True
    # No contact — the item was raised by a registered user, nothing to mail.
    assert should_reply(**{**ok, "has_contact": False}) is False
    # Internal notes never leave the building.
    assert should_reply(**{**ok, "visibility": "internal"}) is False
    # SYSTEM actor = inbound-mail comments / automation comments — no echo loop.
    assert should_reply(**{**ok, "actor_id": SYSTEM_ACTOR_ID}) is False
    # Actorless events (engine clocks) don't speak for anyone.
    assert should_reply(**{**ok, "actor_id": None}) is False
