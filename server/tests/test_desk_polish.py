"""Desk polish (spec 66): canned variables, send_email action, KB deflection.

Pure cases for `render_canned` and the send_email planner's literal/skip
branches; DB-backed cases (test_csat idiom — real services against live
Postgres in a rolled-back transaction) for role-recipient resolution and the
deflect resolved-only filter. Send paths never touch the network:
`radd.smtp.send_message` is monkeypatched.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.automations import engine
from radd.modules.automations.types import ActionType
from radd.modules.canned import service as canned_service
from radd.modules.canned.render import render_canned
from radd.modules.pages import service as docs_service, spaces as docs_spaces
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.mailintake import service as mail_service
from radd.modules.search import deflect
from radd.modules.search.indexer import _TSV_UPDATE
from radd.modules.search.models import SearchIndexRow
from radd.modules.workflow import service as workflow_service
from radd.modules.workflow.types import StateCategory
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine_ = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine_, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine_.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"desk-{uuid.uuid4().hex[:8]}@example.com",
        name="Desk Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def project(db):
    return await projects_service.create_project(
        db, ProjectCreate(key="DP66", name="Desk polish")
    )


@pytest.fixture
def smtp_on(monkeypatch):
    """SMTP configured + captured — never a real send."""
    from radd import smtp as smtp_util

    sent: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(smtp_util, "send_message", lambda *a, **k: sent.append((a, k)))
    return sent


async def _state(db, project, category: StateCategory):
    states = await workflow_service.list_states(db, project.id)
    return next(s for s in states if s.category == category.value)


async def _item(db, admin, project, title, **kwargs):
    return await items_service.create_item(
        db, ItemCreate(project_id=project.id, title=title, **kwargs), admin
    )


# --- render_canned (pure) ---


def test_render_canned_substitutes_every_token():
    ctx = {
        "item.key": "TD-7",
        "item.title": "Printer on fire",
        "reporter.name": "Ada",
        "reporter.email": "ada@example.com",
        "assignee.name": "Grace",
        "me.name": "Hussein",
    }
    body = (
        "Hi {{reporter.name}} <{{reporter.email}}>, re {{item.key}} ({{item.title}}): "
        "{{assignee.name}} is on it. — {{ me.name }}"
    )
    assert render_canned(body, ctx) == (
        "Hi Ada <ada@example.com>, re TD-7 (Printer on fire): Grace is on it. — Hussein"
    )


def test_render_canned_unknown_token_stays_verbatim():
    assert render_canned("see {{custom.field}} and {{nope}}", {"item.key": "TD-1"}) == (
        "see {{custom.field}} and {{nope}}"
    )


def test_render_canned_missing_or_empty_value_leaves_token():
    # No assignee → the router puts "" in ctx → the token stays visible.
    ctx = {"item.key": "TD-1", "assignee.name": ""}
    assert render_canned("{{assignee.name}} / {{reporter.name}}", ctx) == (
        "{{assignee.name}} / {{reporter.name}}"
    )


async def test_render_context_resolves_users_and_leaves_unset_empty(db, admin, project):
    item = await _item(db, admin, project, "toner low")  # reporter = admin, no assignee
    row = await items_service.require_item(db, item.id)
    ctx = await canned_service.render_context(db, row, project, me=admin)
    assert ctx["item.key"] == item.key and ctx["item.title"] == "toner low"
    assert ctx["reporter.name"] == admin.name and ctx["reporter.email"] == admin.email
    assert ctx["assignee.name"] == "" and ctx["me.name"] == admin.name
    # The empty assignee flows through as a verbatim token, not a blank.
    assert render_canned("{{assignee.name}}", ctx) == "{{assignee.name}}"


# --- send_email action (planner + apply) ---


def _send_action(to: str, subject: str = "s {{event_type}}", body: str = "b") -> dict:
    return {"type": ActionType.SEND_EMAIL.value, "params": {"to": to, "subject": subject, "body": body}}


def _plan_kwargs() -> dict:
    return {"facts": engine._manual_facts(), "rule_name": "r"}


async def test_send_email_skips_without_smtp(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    plan = await engine._plan(None, _send_action("ext@example.com"), None, None, None, **_plan_kwargs())
    assert plan.kind == "skip" and "smtp" in plan.detail


async def test_send_email_literal_recipient_renders_templates(smtp_on):
    plan = await engine._plan(None, _send_action("Ext@Example.com "), None, None, None, **_plan_kwargs())
    assert plan.kind == "email"
    # Literal addresses pass through trimmed (case preserved); templates render.
    assert plan.email == ("Ext@Example.com", "", "s manual", "b")


async def test_send_email_role_needs_a_target_item(smtp_on):
    plan = await engine._plan(None, _send_action("reporter"), None, None, None, **_plan_kwargs())
    assert plan.kind == "skip" and "reporter" in plan.detail


async def test_send_email_resolves_roles_from_the_item(db, admin, project, smtp_on):
    item = await _item(db, admin, project, "mail me")  # reporter = admin, no assignee
    row = await items_service.require_item(db, item.id)
    await mail_service.upsert_contact(db, row.id, email="ext@example.com", name="Ext")

    plan = await engine._plan(
        db, _send_action("reporter", subject="Re: {{item.key}}"), row, project, None, **_plan_kwargs()
    )
    assert plan.kind == "email"
    assert plan.email == (admin.email, admin.name, f"Re: {item.key}", "b")

    plan = await engine._plan(db, _send_action("contact"), row, project, None, **_plan_kwargs())
    assert plan.kind == "email" and plan.email[0] == "ext@example.com" and plan.email[1] == "Ext"

    # Unset assignee → the role doesn't resolve → skip-log, never a crash.
    plan = await engine._plan(db, _send_action("assignee"), row, project, None, **_plan_kwargs())
    assert plan.kind == "skip"


async def test_send_email_apply_rides_the_one_transport(db, smtp_on):
    """RADD-983: the action no longer dials `radd.smtp` itself.

    It went through the environment relay directly, so an instance configured
    only through Settings → Email (sender ROWS, no `RADD_SMTP_*`) sent nothing
    and logged nothing. Delivery is `mailintake.service.send_plain_mail` now —
    rows first, environment as the fallback, and the outcome emitted as
    `mail.sent`/`mail.failed`. Every relay ROW is disabled below so the env leg
    is the one that answers — `default_sender` reads the table, not a fixture,
    and a row some other module committed would otherwise decide which relay
    this test dials.
    """
    from sqlalchemy import update

    from radd.modules.mailintake.models import MailSender

    await db.execute(update(MailSender).values(enabled=False))

    plan = await engine._plan(
        None, _send_action("ext@example.com", subject="hello", body="world"), None, None, None,
        **_plan_kwargs(),
    )
    await engine._apply_plan(db, plan, None, None, rule_name="r")

    (args, kwargs), = smtp_on
    assert args == ("ext@example.com", "hello", "world")
    assert kwargs["to_name"] == ""
    # The transport passes a RESOLVED relay rather than letting the helper read
    # the environment for itself — that indirection is the whole fix.
    assert kwargs["config"].host == settings.smtp_host


# --- KB deflection (resolved-only filter + docs seam) ---


async def _index_item(db, project, item) -> None:
    """What the outbox indexer would have written for this item."""
    db.add(
        SearchIndexRow(
            item_id=item.id,
            project_id=project.id,
            key=item.key,
            title=item.title,
        )
    )
    await db.flush()
    await db.execute(_TSV_UPDATE, {"item_id": item.id})


async def test_deflect_items_returns_resolved_only(db, admin, project):
    done = await _state(db, project, StateCategory.DONE)
    canceled = await _state(db, project, StateCategory.CANCELED)
    open_item = await _item(db, admin, project, "printer exploded again")
    done_item = await _item(db, admin, project, "printer exploded before", state_id=done.id)
    canceled_item = await _item(db, admin, project, "printer exploded wontfix", state_id=canceled.id)
    for item in (open_item, done_item, canceled_item):
        await _index_item(db, project, item)

    hits = await deflect.deflect_items(db, project, "printer exploded")
    keys = {hit.key for hit in hits}
    # The open item matches the text but is NOT "previously resolved".
    assert done_item.key in keys and canceled_item.key in keys
    assert open_item.key not in keys

    assert await deflect.deflect_items(db, project, "!!!") == []  # nothing searchable


async def test_deflect_docs_finds_wiki_pages_with_space_names(db, admin):
    space = await docs_spaces.create_space(
        db, PageSpaceCreate(name="Handbook"), admin.id
    )
    page = await docs_service.create_page(
        db,
        PageCreate(space_id=space.id, title="Printer troubleshooting", body="turn it off and on"),
        admin.id,
    )
    docs = await deflect.deflect_docs(db, "printer troubleshooting")
    assert [(doc.id, doc.space_id, doc.space_name) for doc in docs] == [
        (page.id, space.id, "Handbook")
    ]


async def test_deflect_items_fuses_semantic_candidates(db, admin, project, monkeypatch):
    """Spec 106: the items half fuses semantic candidates like the docs half —
    and a semantic OPEN lookalike is re-filtered (deflection means "already
    solved", not "already reported")."""
    from radd.modules.ai.embeddings import candidates

    done = await _state(db, project, StateCategory.DONE)
    fts_hit = await _item(db, admin, project, "printer exploded before", state_id=done.id)
    lookalike = await _item(db, admin, project, "paper output charred", state_id=done.id)
    open_twin = await _item(db, admin, project, "printer smoke plume")
    for item in (fts_hit, lookalike, open_twin):
        await _index_item(db, project, item)

    async def fake_enabled(session):
        return True

    async def fake_candidates(session, q, *, project_ids, exclude_item_id=None, limit):
        assert project_ids == [project.id]
        return [(lookalike.id, 0.1), (open_twin.id, 0.2)]

    monkeypatch.setattr(candidates, "semantic_enabled", fake_enabled)
    monkeypatch.setattr(candidates, "item_candidates", fake_candidates)

    hits = await deflect.deflect_items(db, project, "printer exploded")
    # FTS hit first, then the RESOLVED semantic-only addition; the open twin
    # the (mocked) vector store offered never surfaces.
    assert [hit.key for hit in hits] == [fts_hit.key, lookalike.key]


async def test_deflect_items_degrades_to_fts_when_semantic_fails(
    db, admin, project, monkeypatch
):
    from radd.modules.ai.embeddings import candidates

    done = await _state(db, project, StateCategory.DONE)
    fts_hit = await _item(db, admin, project, "printer exploded before", state_id=done.id)
    await _index_item(db, project, fts_hit)

    async def fake_enabled(session):
        return True

    async def broken(session, q, *, project_ids, exclude_item_id=None, limit):
        raise RuntimeError("provider down")

    monkeypatch.setattr(candidates, "semantic_enabled", fake_enabled)
    monkeypatch.setattr(candidates, "item_candidates", broken)

    hits = await deflect.deflect_items(db, project, "printer exploded")
    assert [hit.key for hit in hits] == [fts_hit.key]
