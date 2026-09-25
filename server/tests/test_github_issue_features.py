"""Behavioral regression coverage for GitHub #25–31 implementation."""

import uuid
from unittest.mock import AsyncMock
import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.dashboards import personal, activity, service
from radd.modules.dashboards.router import replace_widgets
from radd.modules.dashboards.schemas import WidgetLayoutSave, WidgetRead, DashboardCreate
from radd.modules.mailintake.signatures import SignatureRule, detect_rules, detect
from radd.modules.mailintake.quoting import strip_quotes


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def actor(db):
    user = User(
        email=f"features-{uuid.uuid4()}@test.test",
        name="Feature owner",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def test_personal_layout_defaults_persist_and_reject_stale_edits(db):
    user = await actor(db)
    other = await actor(db)
    original = personal.read(user)
    rows = [WidgetRead.model_validate(w) for w in original]
    changed = [{**original[0], "width": 7, "height": 540, "collapsed": True}]
    result = await personal.save(db, user, WidgetLayoutSave(widgets=changed, expected=rows))
    assert result[0]["height"] == 540 and result[0]["width"] == 7
    assert personal.read(other) == original
    assert personal.read(user)[0]["collapsed"]
    with pytest.raises(ConflictError):
        await personal.save(db, user, WidgetLayoutSave(widgets=original, expected=rows))


async def test_shared_layout_atomic_permissions_and_identity(db):
    user = await actor(db)
    dashboard = await service.create_dashboard(db, DashboardCreate(name="Layout"), actor=user)
    payload = {
        "id": str(uuid.uuid4()),
        "widget_type": "slq_count",
        "width": 7,
        "height": 520,
        "config": {"q": ""},
    }
    saved = await replace_widgets(
        dashboard.id, WidgetLayoutSave(widgets=[payload], expected=[]), db, user
    )
    assert saved.widgets[0].width == 7 and saved.widgets[0].height == 520
    saved2 = await replace_widgets(
        dashboard.id,
        WidgetLayoutSave(
            widgets=[{**saved.widgets[0].model_dump(mode="json"), "height": 600}],
            expected=saved.widgets,
        ),
        db,
        user,
    )
    assert saved2.widgets[0].id == saved.widgets[0].id
    with pytest.raises(ConflictError):
        await replace_widgets(
            dashboard.id, WidgetLayoutSave(widgets=[], expected=saved.widgets), db, user
        )


@pytest.mark.parametrize("pattern", ["", "[", ".*", "^", "(?=a)"])
def test_invalid_or_empty_patterns_refused(pattern):
    with pytest.raises(ValidationError):
        SignatureRule(domain="acme.com", pattern=pattern)


def test_domain_matching_boundaries_order_and_inclusion():
    text = "Please investigate.\n\nFooter\nEngineering\nperson@acme.com"
    rule = SignatureRule(domain="acme.com", pattern="^Footer$")
    assert detect_rules(text, "a@acme.com", [rule])[0] == "Footer\nEngineering\nperson@acme.com"
    assert detect_rules(text, "a@notacme.com", [rule])[0] is None
    assert detect_rules(text, "a@sub.acme.com", [rule])[0] is None
    assert detect_rules(
        text, "a@sub.acme.com", [rule.model_copy(update={"include_subdomains": True})]
    )[0]
    assert detect_rules("Footer\nEngineering", "a@acme.com", [rule])[0] is None


@pytest.mark.parametrize(
    "body",
    [
        "Please call +1 555 123 4567",
        "Thanks",
        "Please send to person@acme.com",
        "Request\n\nRegards,\nSam\nP.S. Please also fix the login.",
    ],
)
def test_legitimate_content_kept(body):
    assert detect_rules(body, "sender@acme.com", [])[0] is None


@pytest.mark.parametrize(
    "sig", ["Best regards,\nSam Jones\nsam@acme.com", "Sent from my iPhone", "-- \nSam"]
)
def test_builtin_signature_exact_suffix(sig):
    body = "Please fix login.\n\n" + sig
    assert detect_rules(body, "sender@acme.com", [])[0] == sig
    assert strip_quotes(body, strip_signature=False) == body.strip()


async def test_ai_requires_exact_suffix_and_fails_open(db, monkeypatch):
    from radd.modules.ai import features, client

    monkeypatch.setattr(features, "feature_enabled", AsyncMock(return_value=True))
    fake = AsyncMock(return_value={"signature": "Invented text"})
    monkeypatch.setattr(client, "complete_structured", fake)
    body = "Investigate login.\n\nCustom Footer\nSam"
    assert (await detect(db, body, "a@acme.com", rules=[]))[0] is None
    fake.return_value = {"signature": "Custom Footer\nSam"}
    assert (await detect(db, body, "a@acme.com", rules=[]))[0] == "Custom Footer\nSam"
    fake.side_effect = TimeoutError()
    assert (await detect(db, body, "a@acme.com", rules=[]))[0] is None
    fake.reset_mock()
    await detect(db, body, "a@acme.com", rules=[], use_ai=False)
    fake.assert_not_awaited()


async def test_activity_excludes_automation_and_checks_current_access(db, monkeypatch):
    from radd.modules.events.models import Event

    user = await actor(db)
    item_id = uuid.uuid4()
    for automated in [True, False]:
        db.add(
            Event(
                actor_id=user.id,
                automated=automated,
                event_type="item.created",
                entity_type="item",
                entity_id=str(item_id),
                payload={},
            )
        )
    await db.flush()
    check = AsyncMock(side_effect=NotFoundError("item", item_id))
    monkeypatch.setattr(activity, "require_readable_item", check)
    result = await activity.read(db, user)
    assert result["entries"] == []
    assert check.await_count == 1


async def test_mail_new_ticket_and_reply_keep_reversible_signatures(db, monkeypatch):
    from email.message import EmailMessage
    from sqlalchemy import select
    from radd.modules.projects import service as projects
    from radd.modules.projects.schemas import ProjectCreate
    from radd.modules.mailintake import intake, parsing
    from radd.modules.items.models import WorkItem
    from radd.modules.comments.models import Comment
    from radd.modules.mailintake.signature_router import restore

    monkeypatch.setattr(intake, "MAIL_RAW_RETENTION_DAYS", 0)
    user = await actor(db)
    project = await projects.create_project(
        db, ProjectCreate(key="SIG" + uuid.uuid4().hex[:5].upper(), name="Signatures")
    )
    original = "Please fix login.\n\nBest regards,\nSam Jones\nsam@acme.com"

    async def accept(message_id, subject):
        message = EmailMessage()
        message["From"] = "Sam <sam@acme.com>"
        message["To"] = "help@example.test"
        message["Subject"] = subject
        message["Message-ID"] = message_id
        message.set_content(original)
        blob = message.as_bytes()
        return await intake.accept(
            db,
            parsing.parse_email(blob),
            raw=blob,
            default_project_key=project.key,
            own_addresses={"help@example.test"},
        )

    outcome = await accept("<first@signature.test>", "Login fails")
    item = await db.get(WorkItem, outcome.item_id)
    assert item.description.endswith("sam@acme.com")
    assert item.email_signature.startswith("Best regards,")
    await accept("<reply@signature.test>", "Re: " + outcome.item_key)
    comment = await db.scalar(select(Comment).where(Comment.entity_id == item.id))
    assert comment.email_signature.startswith("Best regards,")
    assert comment.body.endswith("sam@acme.com")
    await restore("item", item.id, db, user)
    assert item.email_signature is None and "sam@acme.com" in item.description
    await restore("comment", comment.id, db, user)
    assert comment.email_signature is None and "sam@acme.com" in comment.body


def test_expensive_domain_regex_preserves_body():
    rule = SignatureRule(domain="acme.com", pattern=r"(a|aa)+$")
    signature, reason = detect_rules("a" * 10000 + "!", "a@acme.com", [rule])
    assert signature is None and "timed out" in reason


async def test_activity_reports_own_actions_and_paginates(db):
    from radd.modules.items import service as items
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.comments import service as comments
    from radd.modules.comments.schemas import CommentCreate
    from radd.modules.projects import service as projects
    from radd.modules.projects.schemas import ProjectCreate

    user = await actor(db)
    other = await actor(db)
    project = await projects.create_project(
        db, ProjectCreate(key="ACT" + uuid.uuid4().hex[:5].upper(), name="Activity")
    )
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="Personal activity"), user
    )
    comment = await comments.create_comment(db, item.id, CommentCreate(body="My note"), user)
    await comments.create_comment(db, item.id, CommentCreate(body="Other person's note"), other)
    first = await activity.read(db, user, limit=1)
    assert first["entries"][0]["action"] == "Commented"
    assert first["entries"][0]["comment_id"] == str(comment.id)
    assert first["entries"][0]["item_key"] == item.key
    assert first["next"]
    second = await activity.read(db, user, before=first["next"])
    assert second["entries"][0]["action"] == "Created issue"
    assert second["entries"][0]["id"] < first["entries"][0]["id"]
    assert (await activity.read(db, user, project_id=uuid.uuid4()))["entries"] == []
