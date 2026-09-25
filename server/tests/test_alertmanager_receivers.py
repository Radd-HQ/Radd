"""RADD-1317: Alertmanager receivers are rows, and a receiver records the alert
and fires its triggers — it comments, labels and transitions nothing.

The old receiver commented on every repeat and resolution, labelled every issue
`alert`, and moved a resolved alert's issue to an env-named state. The project
below HAS a Done state an old-style resolve could have moved to, so "the state
did not move" is not vacuous; those behaviours are this plugin's templates now.
"""

import uuid

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.alertmanager import service
from radd.modules.alertmanager.router import router
from radd.modules.alertmanager.schemas import ReceiverCreate, ReceiverUpdate
from radd.modules.alertmanager.types import AlertmanagerEvent, AlertTrigger
from radd.modules.comments.types import CommentEvent
from radd.modules.events.models import Event
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEvent
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


def _app(db) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def _session():
        yield db

    app.dependency_overrides[get_session] = _session

    @app.exception_handler(ForbiddenError)
    async def _forbidden(_request, exc):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    return app


async def _events(db, head: int, event_type: str) -> list[Event]:
    rows = await db.execute(select(Event).where(Event.id > head, Event.event_type == event_type).order_by(Event.id))
    return list(rows.scalars())


def _alert(status: str, fingerprint: str) -> dict:
    return {
        "status": status,
        "labels": {"alertname": "DiskFull", "instance": "farm-03"},
        "annotations": {"summary": "/ at 98%"},
        "fingerprint": fingerprint,
    }


async def test_firing_repeat_and_resolve_fire_triggers_and_change_nothing_else(db):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"AM{uuid.uuid4().hex[:4].upper()}", name="Alerts")
    )
    token = uuid.uuid4().hex
    receiver = await service.create_receiver(
        db, ReceiverCreate(name=f"prod-{uuid.uuid4().hex[:6]}", token=token, project_id=project.id)
    )
    fingerprint = uuid.uuid4().hex
    head = (await db.execute(select(Event.id).order_by(Event.id.desc()).limit(1))).scalar() or 0

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db)), base_url="http://t") as client:
        url = f"/integrations/alertmanager?token={token}"
        first = await client.post(url, json={"alerts": [_alert("firing", fingerprint)]})
        again = await client.post(url, json={"alerts": [_alert("firing", fingerprint)]})
        resolved = await client.post(url, json={"alerts": [_alert("resolved", fingerprint)]})
    assert first.json() == {"created": 1, "triggered": 1}
    assert again.json() == {"created": 0, "triggered": 1}
    assert resolved.json() == {"created": 0, "triggered": 1}

    [firing] = await _events(db, head, AlertTrigger.FIRING.value)
    created = await items_service.require_item(db, uuid.UUID(firing.payload["item"]["id"]))
    initial_state = created.state_id
    item = await items_service.require_item(db, uuid.UUID(firing.payload["item"]["id"]))
    assert item.project_id == project.id and item.title == "DiskFull: / at 98%"
    assert firing.payload["alertname"] == "DiskFull" and firing.payload["receiver"] == receiver.name
    [repeated] = await _events(db, head, AlertTrigger.REPEATED.value)
    [done] = await _events(db, head, AlertTrigger.RESOLVED.value)
    assert repeated.payload["item"]["id"] == done.payload["item"]["id"] == str(item.id)
    assert done.payload["status"] == "resolved"

    # Nothing acted on the issue: no comment, no label, no transition.
    assert await _events(db, head, CommentEvent.CREATED.value) == []
    assert await _events(db, head, ItemEvent.UPDATED.value) == []
    assert (await items_service.require_item(db, item.id)).state_id == initial_state


async def test_an_inactive_receiver_or_a_wrong_token_is_refused(db):
    token = uuid.uuid4().hex
    receiver = await service.create_receiver(db, ReceiverCreate(name=f"off-{uuid.uuid4().hex[:6]}", token=token))
    await service.update_receiver(db, receiver.id, ReceiverUpdate(active=False))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db)), base_url="http://t") as client:
        inactive = await client.post(f"/integrations/alertmanager?token={token}", json={"alerts": []})
        wrong = await client.post("/integrations/alertmanager?token=nope", json={"alerts": []})
    assert inactive.status_code == wrong.status_code == 403


async def test_an_empty_token_on_update_keeps_the_stored_one_and_the_diff_hides_it(db):
    token = uuid.uuid4().hex
    receiver = await service.create_receiver(db, ReceiverCreate(name=f"keep-{uuid.uuid4().hex[:6]}", token=token))
    await service.update_receiver(db, receiver.id, ReceiverUpdate(token="", name=receiver.name + "-x"))
    assert receiver.token == token
    head = (await db.execute(select(Event.id).order_by(Event.id.desc()).limit(1))).scalar() or 0
    await service.update_receiver(db, receiver.id, ReceiverUpdate(token="another-secret"))
    [updated] = await _events(db, head, AlertmanagerEvent.RECEIVER_UPDATED.value)
    assert "another-secret" not in str(updated.payload) and token not in str(updated.payload)
    assert [c["field"] for c in updated.payload["changes"]] == ["token"]
