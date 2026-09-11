"""Realtime delivery predicate (specs 27/86).

Pure tests of `should_deliver` — the one rule that decides who sees which push.
Spec 86 stage 1: authenticated connections receive every entity frame (frames
are payload-free pings; the refetched endpoints are RBAC'd); notification
frames stay private to their recipient. The socket lifecycle itself is
exercised by connecting a browser (or wscat) to a running server.
"""

import uuid

from radd.modules.realtime.hub import ClientInfo, should_deliver

USER = uuid.uuid4()
OTHER = uuid.uuid4()


class StubEvent:
    """Duck-types events.models.Event for the predicate."""

    def __init__(self, entity_type: str, payload=None):
        self.entity_type = entity_type
        self.payload = payload or {}


def test_entity_frames_reach_every_authenticated_connection():
    # Every entity frame reaches every authenticated connection (spec 86).
    assert should_deliver(ClientInfo(user_id=USER), StubEvent("item")) is True
    assert should_deliver(ClientInfo(user_id=USER), StubEvent("user")) is True


def test_notifications_are_private_to_their_recipient():
    event = StubEvent("notification", {"user_id": str(USER)})
    assert should_deliver(ClientInfo(user_id=USER), event) is True
    # A different authenticated user never gets someone else's notification signal.
    assert should_deliver(ClientInfo(user_id=OTHER), event) is False


async def test_slow_connection_does_not_hold_up_a_healthy_reader(monkeypatch):
    import asyncio
    from radd.config import settings
    from radd.modules.realtime import broadcaster
    from radd.modules.realtime.hub import hub

    delivered = asyncio.Event()
    class Socket:
        def __init__(self, slow=False):
            self.slow = slow
        async def send_json(self, message):
            if self.slow:
                await asyncio.sleep(30)
            else:
                delivered.set()
        async def close(self):
            pass
    slow, healthy = Socket(True), Socket()
    monkeypatch.setattr(settings, "realtime_send_timeout", .15)
    monkeypatch.setattr(hub, "connections", {slow: ClientInfo(USER), healthy: ClientInfo(OTHER)})
    event = StubEvent("item")
    event.event_type = "item.updated"
    task = asyncio.create_task(broadcaster._fan_out(event))
    await asyncio.wait_for(delivered.wait(), .1)
    await task
    assert slow not in hub.connections
    assert healthy in hub.connections


def test_burst_coalescing_preserves_private_recipients_and_skips_imports():
    from radd.modules.realtime.broadcaster import _coalesce

    events = [StubEvent("item") for _ in range(200)]
    events += [StubEvent("notification", {"user_id": str(user)}) for user in (USER, OTHER)]
    for event in events:
        event.silent = False
    events[0].silent = True
    assert len(_coalesce(events)) == 3


def test_project_subscriptions_target_only_interested_authorized_queries():
    from radd.modules.realtime.hub import query_targets, validate_subscriptions

    queries = [
        {"id": "view-A", "entities": ["item"], "project_id": "A"},
        {"id": "view-B", "entities": ["item"], "project_id": "B"},
        {"id": "all-projects", "entities": ["item"]},
        {"id": "forbidden", "entities": ["item"], "project_id": "private"},
    ]
    info = ClientInfo(USER, validate_subscriptions(queries, {"A", "B"}))
    event = StubEvent("item", {"item": {"project": {"id": "A"}}})
    assert query_targets(info, event) == ["view-A", "all-projects"]
    assert query_targets(info, StubEvent("item", {"project_id": "B"})) == ["view-B", "all-projects"]
    assert query_targets(info, StubEvent("role")) == []


def test_two_socket_readers_receive_comment_changes_and_revocation(monkeypatch):
    """Real sessions, comment outbox rows and ASGI WebSockets share the delivery path."""
    import asyncio
    import importlib
    import pytest
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from starlette.websockets import WebSocketDisconnect

    from radd.config import settings
    from radd.modules.auth import service as auth
    from radd.modules.auth.models import User
    from radd.modules.auth.types import SESSION_COOKIE_NAME
    from radd.modules.comments import service as comments
    from radd.modules.comments.schemas import CommentCreate, CommentUpdate
    from radd.modules.events import service as events
    from radd.modules.items import service as items
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.projects import service as projects
    from radd.modules.projects.schemas import ProjectCreate
    from radd.modules.realtime.broadcaster import _fan_out
    from radd.modules.realtime.hub import hub

    sockets = importlib.import_module("radd.modules.realtime.router")
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(sockets, "SessionLocal", sessions)
    monkeypatch.setattr(hub, "connections", {})
    app = FastAPI()
    app.include_router(sockets.router)

    async def setup():
        async with sessions() as db:
            user = User(email=f"ws-{uuid.uuid4()}@example.com", name="Reader", instance_role="admin")
            db.add(user)
            await db.flush()
            project = await projects.create_project(
                db, ProjectCreate(key=f"WS{uuid.uuid4().hex[:6].upper()}", name="Socket test"),
                actor_id=user.id,
            )
            item = await items.create_item(db, ItemCreate(project_id=project.id, title="Thread"), actor=user)
            cookies = [await auth.create_session(db, user) for _ in range(2)]
            await db.commit()
            return user.id, item.id, cookies

    async def subscribed():
        async with asyncio.timeout(3):
            while len(hub.connections) != 2 or any(
                info.subscriptions is None for info in hub.connections.values()
            ):
                await asyncio.sleep(.01)

    async def change(action, comment_id=None):
        async with sessions() as db:
            user = await db.get(User, user_id)
            cursor = await events.latest_event_id(db)
            if action == "created":
                comment = await comments.create_comment(db, item_id, CommentCreate(body="First"), user)
                comment_id = comment.id
            elif action == "updated":
                await comments.update_comment(db, comment_id, CommentUpdate(body="Edited"), user)
            else:
                await comments.delete_comment(db, comment_id, user)
            await db.commit()
            batch = await events.read_after(db, cursor, 100)
            matching = [event for event in batch if event.event_type == f"comment.{action}"]
            assert len(matching) == 1
            await _fan_out(matching[0])
            return comment_id

    async def revoke(cookie):
        async with sessions() as db:
            await auth.delete_session_by_token(db, cookie)
            await db.commit()

    with TestClient(app) as client:
        try:
            user_id, item_id, cookies = client.portal.call(setup)
            with client.websocket_connect("/ws", cookies={SESSION_COOKIE_NAME: cookies[0]}) as first:
                with client.websocket_connect("/ws", cookies={SESSION_COOKIE_NAME: cookies[1]}) as second:
                    for socket in (first, second):
                        socket.send_json({"queries": [{"id": "thread", "entities": ["comment"]}]})
                    client.portal.call(subscribed)
                    comment_id = None
                    for action in ("created", "updated", "deleted"):
                        comment_id = client.portal.call(change, action, comment_id)
                        for socket in (first, second):
                            assert socket.receive_json() == {
                                "entity": "comment", "event_type": f"comment.{action}", "queries": ["thread"],
                            }
                    client.portal.call(revoke, cookies[0])
                    first.send_json({"queries": []})
                    with pytest.raises(WebSocketDisconnect) as closed:
                        first.receive_json()
                    assert closed.value.code == 4401
        finally:
            client.portal.call(engine.dispose)
