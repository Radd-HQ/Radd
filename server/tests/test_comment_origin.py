"""RADD-1318: a comment records where it came from, and the requester relay
decides by that — not by "the author is the SYSTEM user". Against live Postgres:
an automation's public comment reaches the requester; the requester's own mail,
filed with no account behind it, is never echoed; a resolution alone sends
nothing while `mail_send_resolved` is off.
"""

import uuid
from types import SimpleNamespace

import pytest

from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.comments import service as comments_service
from radd.modules.comments.models import Comment
from radd.modules.comments.schemas import CommentCreate
from radd.modules.comments.types import CommentEntity, CommentEvent, CommentOrigin
from radd.modules.events import service as events_service
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEvent
from radd.modules.items.schemas import ItemCreate
from radd.modules.mailintake import outbound, service as mail_service
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def ticket(db):
    """An issue with an external email contact — someone the relay can mail."""
    agent = User(email=f"agent-{uuid.uuid4().hex[:8]}@example.com", name="Ada", instance_role=InstanceRole.ADMIN.value)
    db.add(agent)
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"CO{uuid.uuid4().hex[:4].upper()}", name="Origins")
    )
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="Printer on fire"), agent)
    await mail_service.upsert_contact(db, item.id, email="cass@vip.example.com", name="Cass")
    return agent, item


async def _event_of(db, comment_id) -> events_service.Event:
    [event] = await events_service.query_events(
        db, entity_type=CommentEntity.COMMENT.value, entity_id=str(comment_id),
        event_types=[CommentEvent.CREATED.value], limit=1,
    )
    return event


async def test_an_automations_public_comment_is_relayed_to_the_requester(db, ticket):
    agent, item = ticket
    # An automation acting AS a real person (`act_as`) — the author is Ada, the
    # origin is still the automation, derived from the marker.
    with events_service.automated():
        comment = await comments_service.create_comment(
            db, item.id, CommentCreate(body="We're on it."), agent
        )
    row = await db.get(Comment, comment.id)
    assert row.origin == CommentOrigin.AUTOMATION.value
    event = await _event_of(db, comment.id)
    assert event.payload["origin"] == CommentOrigin.AUTOMATION.value

    planned = await outbound._plan_reply(db, event)
    assert planned is not None, "the automation's reply never reached the customer — the RADD-1318 bug"
    assert [r.email for r in planned.recipients] == ["cass@vip.example.com"]


async def test_a_system_authored_automation_comment_is_relayed_too(db, ticket):
    """The shape the old gate refused outright: SYSTEM author, public body."""
    _agent, item = ticket
    system = await auth_service.get_user(db, SYSTEM_ACTOR_ID)
    with events_service.automated():
        comment = await comments_service.create_comment(db, item.id, CommentCreate(body="Received."), system)
    assert await outbound._plan_reply(db, await _event_of(db, comment.id)) is not None


async def test_the_requesters_own_mail_is_never_echoed_back(db, ticket):
    _agent, item = ticket
    system = await auth_service.get_user(db, SYSTEM_ACTOR_ID)
    comment = await comments_service.create_comment(
        db, item.id, CommentCreate(body="Email reply from Cass: still broken"), system,
        origin=CommentOrigin.INBOUND_MAIL,
    )
    event = await _event_of(db, comment.id)
    assert event.payload["origin"] == CommentOrigin.INBOUND_MAIL.value
    assert await outbound._plan_reply(db, event) is None


async def test_a_person_typing_has_no_origin(db, ticket):
    agent, item = ticket
    comment = await comments_service.create_comment(db, item.id, CommentCreate(body="Looking now."), agent)
    assert (await db.get(Comment, comment.id)).origin is None
    assert await outbound._plan_reply(db, await _event_of(db, comment.id)) is not None


async def test_resolving_an_issue_sends_the_requester_nothing_by_itself(db, ticket, monkeypatch):
    """With `mail_send_resolved` at its default (OFF, RADD-1368) the consumer plans
    nothing for a done move, even with a sender configured — which is what makes
    the absence non-vacuous."""

    async def configured(_session):
        return True

    monkeypatch.setattr(mail_service, "outbound_configured", configured)
    _agent, item = ticket
    moved_to_done = SimpleNamespace(
        event_type=ItemEvent.UPDATED.value,
        entity_id=str(item.id),
        actor_id=None,
        payload={
            "item": {"id": str(item.id), "state": {"name": "Done", "category": "done"}},
            "changes": [{"field": "state", "from": "In Progress", "to": "Done"}],
        },
    )
    assert await outbound._plan(db, moved_to_done) is None
