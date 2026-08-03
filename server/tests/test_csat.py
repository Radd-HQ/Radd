"""CSAT surveys (spec 65), driven through the real services against live
Postgres in a rolled-back transaction (test_public_forms idiom):

- sender decision: setting off / SMTP off / no recipient → skip; the mail
  contact beats the reporter; one survey per item lifetime (reopen→re-resolve
  never resends). Events come from REAL item.updated emissions so the payload
  shape assumption (changes diff + state embed w/ category) stays verified.
- public flow: unknown token 404, rating bounds 422, responded_at stamped once,
  re-submits allowed (latest wins), csat.responded emitted.
- report: csat_avg/csat_count ride the /reports/sla buckets by responded week.

Send paths never touch the network: `radd.smtp.send_message` is monkeypatched.
"""

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.csat import sender, service as csat_service
from radd.modules.csat.schemas import PublicCsatSubmit
from radd.modules.csat.types import CsatEvent
from radd.modules.events import service as events_service
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEntity, ItemEvent
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.mailintake import service as mail_service
from radd.modules.reporting import service as reporting
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope
from radd.modules.workflow import service as workflow_service
from radd.modules.workflow.types import StateCategory
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"csat-{uuid.uuid4().hex[:8]}@example.com",
        name="CSAT Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def project(db):
    return await projects_service.create_project(
        db, ProjectCreate(key="CS65", name="Service desk")
    )


@pytest.fixture
def smtp_on(monkeypatch):
    """SMTP configured + captured — never a real send."""
    from radd import smtp as smtp_util

    sent: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(smtp_util, "send_message", lambda *a, **k: sent.append((a, k)))
    return sent


async def _enable_csat(db, project) -> None:
    await settings_service.set_value(
        db, SettingKey.CSAT_ENABLED, SettingScope.PROJECT, project.id, True
    )


async def _state(db, project, category: StateCategory):
    states = await workflow_service.list_states(db, project.id)
    return next(s for s in states if s.category == category.value)


async def _resolve(db, admin, project, item_id):
    """Move the item into a done-category state; return the REAL item.updated event."""
    done = await _state(db, project, StateCategory.DONE)
    await items_service.update_item(db, item_id, ItemUpdate(state_id=done.id), admin)
    rows = await events_service.query_events(
        db,
        entity_type=ItemEntity.ITEM.value,
        entity_id=str(item_id),
        event_types=[ItemEvent.UPDATED.value],
        limit=1,
    )
    return rows[0]


async def _item(db, admin, project, **kwargs):
    return await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="printer on fire", **kwargs), admin
    )


# --- sender decision ---


def test_moved_to_done_is_pure_over_the_payload():
    done_state = {"category": StateCategory.DONE.value}
    assert sender.moved_to_done({"changes": [{"field": "state"}], "state": done_state})
    # No state change in the diff (e.g. an assignee edit while already done).
    assert not sender.moved_to_done({"changes": [{"field": "assignee"}], "state": done_state})
    # State moved, but not INTO done.
    assert not sender.moved_to_done(
        {"changes": [{"field": "state"}], "state": {"category": StateCategory.IN_PROGRESS.value}}
    )
    assert not sender.moved_to_done({})  # create-shaped payload: no changes at all


async def test_sender_skips_when_setting_off(db, admin, project, smtp_on):
    item = await _item(db, admin, project)
    event = await _resolve(db, admin, project, item.id)
    assert await sender.process_event(db, event) is None  # csat_enabled defaults False
    assert await csat_service.survey_for_item(db, item.id) is None


async def test_sender_skips_without_smtp(db, admin, project, monkeypatch):
    await _enable_csat(db, project)
    monkeypatch.setattr(settings, "smtp_host", "")
    item = await _item(db, admin, project)
    event = await _resolve(db, admin, project, item.id)
    assert await sender.process_event(db, event) is None
    assert await csat_service.survey_for_item(db, item.id) is None


async def test_sender_prefers_contact_over_reporter(db, admin, project, smtp_on):
    await _enable_csat(db, project)
    item = await _item(db, admin, project)  # reporter = admin
    await mail_service.upsert_contact(db, item.id, email="ext@example.com", name="Ext")
    event = await _resolve(db, admin, project, item.id)

    email = await sender.process_event(db, event)
    assert email is not None
    assert email.email == "ext@example.com" and email.name == "Ext"
    assert item.key in email.subject

    survey = await csat_service.survey_for_item(db, item.id)
    assert survey is not None and survey.rating is None and survey.responded_at is None
    # Five one-click links into the PUBLIC SPA page, one per rating.
    for rating in range(1, 6):
        assert f"{settings.app_base_url}/public/csat/{survey.token}?rating={rating}" in email.body
    requested = await events_service.query_events(
        db,
        entity_type=ItemEntity.ITEM.value,
        entity_id=str(item.id),
        event_types=[CsatEvent.REQUESTED.value],
    )
    assert len(requested) == 1 and requested[0].actor_id is None
    assert requested[0].payload["key"] == item.key


async def test_sender_falls_back_to_reporter_and_sends_once_only(db, admin, project, smtp_on):
    await _enable_csat(db, project)
    item = await _item(db, admin, project)  # no contact; reporter = admin (active)
    event = await _resolve(db, admin, project, item.id)

    email = await sender.process_event(db, event)
    assert email is not None and email.email == admin.email

    # Same event again (redelivery) and a reopen→re-resolve: both skipped.
    assert await sender.process_event(db, event) is None
    todo = await _state(db, project, StateCategory.TODO)
    await items_service.update_item(db, item.id, ItemUpdate(state_id=todo.id), admin)
    re_resolved = await _resolve(db, admin, project, item.id)
    assert sender.moved_to_done(re_resolved.payload)  # the event qualifies…
    assert await sender.process_event(db, re_resolved) is None  # …but the row guards


async def test_sender_skips_without_recipient(db, admin, project, smtp_on):
    await _enable_csat(db, project)
    # Explicit-null reporter (spec 62 idiom — an intake/public item) and no contact.
    item = await _item(db, admin, project, reporter_id=None)
    event = await _resolve(db, admin, project, item.id)
    assert await sender.process_event(db, event) is None
    assert await csat_service.survey_for_item(db, item.id) is None


# --- public flow ---


async def test_public_flow_latest_wins_responded_stamped_once(db, admin, project):
    item = await _item(db, admin, project)
    survey = await csat_service.create_survey(
        db, item_id=item.id, item_key=item.key
    )

    rendered = await csat_service.public_survey(db, survey.token)
    assert rendered.item_key == item.key and rendered.item_title == item.title
    assert rendered.rating is None and rendered.responded_at is None
    # Unanswered → the item-scoped read stays 404-quiet.
    with pytest.raises(NotFoundError):
        await csat_service.responded_survey(db, item.id)

    first = await csat_service.record_response(
        db, survey.token, PublicCsatSubmit(rating=4, comment="great")
    )
    assert first.rating == 4 and first.responded_at is not None
    stamped = first.responded_at

    # Re-submit: latest wins, the response stamp does NOT move.
    second = await csat_service.record_response(
        db, survey.token, PublicCsatSubmit(rating=2, comment="on reflection…")
    )
    assert second.rating == 2 and second.responded_at == stamped

    answered = await csat_service.responded_survey(db, item.id)
    assert answered.rating == 2 and answered.comment == "on reflection…"

    responded = await events_service.query_events(
        db,
        entity_type=ItemEntity.ITEM.value,
        entity_id=str(item.id),
        event_types=[CsatEvent.RESPONDED.value],
        ascending=True,
    )
    assert [e.payload["rating"] for e in responded] == [4, 2]
    assert all(e.actor_id is None for e in responded)


async def test_public_unknown_token_is_404(db):
    with pytest.raises(NotFoundError):
        await csat_service.public_survey(db, "not-a-real-token")
    with pytest.raises(NotFoundError):
        await csat_service.record_response(db, "not-a-real-token", PublicCsatSubmit(rating=5))


def test_public_submit_rating_bounds_and_comment_cap():
    for bad in (0, 6):
        with pytest.raises(ValidationError):
            PublicCsatSubmit(rating=bad)
    with pytest.raises(ValidationError):
        PublicCsatSubmit(rating=3, comment="x" * 2001)
    assert PublicCsatSubmit(rating=3, comment="x" * 2000).rating == 3


# --- report aggregation ---


async def test_sla_report_carries_csat_by_responded_week(db, admin, project):
    for rating in (5, 3):
        item = await _item(db, admin, project)
        survey = await csat_service.create_survey(
            db, item_id=item.id, item_key=item.key
        )
        await csat_service.record_response(db, survey.token, PublicCsatSubmit(rating=rating))

    buckets = (await reporting.sla_report(db, None, weeks=2)).buckets
    assert sum(b.csat_count for b in buckets) == 2
    week = next(b for b in buckets if b.csat_count)
    assert week.csat_avg == pytest.approx(4.0)
    # Weeks without responses stay None/0, and other projects see nothing.
    assert all(b.csat_avg is None for b in buckets if b.csat_count == 0)
    empty = (await reporting.sla_report(db, uuid.uuid4(), weeks=2)).buckets
    assert sum(b.csat_count for b in empty) == 0
