"""Spec 122 (RADD-1161): one live document, many editors — the server half.

Real sessions, a real page and real ASGI WebSockets speaking the y-websocket
protocol through pycrdt's own encoders, over the collab + pages routers on a
bare app (the `test_realtime.py` shape). Everything the room is for is asserted
here: two editors converge, an observer's update is dropped, the seed grant is
handed out once and passes on, a stale stored state is discarded, an outside
PATCH is refused while an editor is connected and accepted after, the history
window coalesces, the anonymous caller and the read-only member are refused.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pycrdt import (
    Awareness,
    Doc,
    Text,
    YMessageType,
    YSyncMessageType,
    create_awareness_message,
    create_sync_message,
    create_update_message,
    handle_sync_message,
    read_message,
)
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketDisconnect

from radd.config import settings
from radd.exceptions import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from radd.modules.auth import grants as role_grants, roles as roles_service, service as auth
from radd.modules.auth.models import Role, User
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import SESSION_COOKIE_NAME, InstanceRole, Permission
from radd.modules.collab import store
from radd.modules.collab.rooms import hub
from radd.modules.collab.router import router as collab_router
from radd.modules.collab.types import (
    WS_CLOSE_SESSION_UNKNOWN,
    WS_CLOSE_UNAUTHENTICATED,
    CollabRole,
    YClientMessage,
)
from radd.modules.pages import service as pages_service, spaces
from radd.modules.pages.models import PageSpace, PageVersion
from radd.modules.pages.router import router as pages_router
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate

API = settings.api_prefix


def _app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        await hub.start()
        yield
        await hub.shutdown()

    app = FastAPI(lifespan=lifespan)
    for exc_type, status in (
        (NotFoundError, 404),
        (ConflictError, 409),
        (UnauthorizedError, 401),
        (ForbiddenError, 403),
    ):

        def handler(request: Request, exc: Exception, status=status) -> JSONResponse:
            return JSONResponse(status_code=status, content={"detail": str(exc)})

        app.add_exception_handler(exc_type, handler)
    app.include_router(collab_router, prefix=API)
    app.include_router(pages_router, prefix=API)
    return app


async def _stage() -> dict:
    """Two admins (Ada, Grace), a read-only member, a space and a page — committed,
    because the socket handlers open their own sessions."""
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        people = {}
        for key, name, role in (
            ("ada", "Ada", InstanceRole.ADMIN),
            ("grace", "Grace", InstanceRole.ADMIN),
            ("reader", "Reader", InstanceRole.MEMBER),
        ):
            user = User(email=f"cl-{uuid.uuid4().hex[:8]}@example.com", name=name, instance_role=role.value)
            db.add(user)
            await db.flush()
            people[key] = user
        space = await spaces.create_space(
            db, PageSpaceCreate(name="Lab", slug=f"lab-{uuid.uuid4().hex[:6]}"), people["ada"].id
        )
        page = await pages_service.create_page(
            db, PageCreate(space_id=space.id, title="Notes", body="first"), people["ada"].id
        )
        reader_role = await roles_service.create_role(
            db,
            RoleCreate(key=f"cl-{uuid.uuid4().hex[:8]}", name="Reader", permissions=[str(Permission.PAGE_READ)]),
        )
        await role_grants.create_grant(db, reader_role.id, user_id=people["reader"].id, space_id=space.id)
        cookies = {key: await auth.create_session(db, user) for key, user in people.items()}
        await db.commit()
        page_id, space_id, role_id = page.id, space.id, reader_role.id
    await engine.dispose()
    return {
        "page_id": page_id,
        "cookies": cookies,
        "users": {k: u.id for k, u in people.items()},
        "space_id": space_id,
        "role_id": role_id,
    }


async def _unstage(s: dict) -> None:
    """The rows were COMMITTED (the socket handlers read them from their own
    sessions), so they leave the shared test database here, not by rollback —
    `test_space_scope` asserts the exact set of spaces an unscoped grant reaches."""
    await hub.invalidate(s["page_id"])  # the room first: it would otherwise persist into a deleted page
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine)() as db:
        await db.execute(delete(PageSpace).where(PageSpace.id == s["space_id"]))  # cascades pages + grants
        await db.execute(delete(Role).where(Role.id == s["role_id"]))
        await db.execute(delete(User).where(User.id.in_(list(s["users"].values()))))  # cascades sessions
        await db.commit()
    await engine.dispose()


@pytest.fixture
def stage():
    with TestClient(_app()) as client:
        s = client.portal.call(_stage)
        try:
            yield client, s
        finally:
            client.portal.call(_unstage, s)


# --- protocol helpers -----------------------------------------------------------


def _join(client, page_id, cookie, role=CollabRole.EDITOR):
    response = client.post(
        f"{API}/collab/pages/{page_id}/join", json={"role": role}, cookies={SESSION_COOKIE_NAME: cookie}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _connect(client, page_id, cookie, session):
    return client.websocket_connect(
        f"{API}/collab/pages/{page_id}?session={session}", cookies={SESSION_COOKIE_NAME: cookie}
    )


def _handshake(socket, doc: Doc) -> None:
    """What y-websocket does on connect: answer the server's step 1 with our
    step 2, ask with our own step 1, apply the server's step 2."""
    step1 = socket.receive_bytes()
    assert step1[0] == YMessageType.SYNC and step1[1] == YSyncMessageType.SYNC_STEP1
    socket.send_bytes(handle_sync_message(step1[1:], doc))
    socket.send_bytes(create_sync_message(doc))
    _apply(socket, doc)


def _apply(socket, doc: Doc) -> bytes:
    frame = socket.receive_bytes()
    if frame[0] == YMessageType.SYNC:
        handle_sync_message(frame[1:], doc)
    return frame


def _type(socket, doc: Doc, text: str) -> None:
    """A local edit, sent as the update it produced."""
    updates: list[bytes] = []
    subscription = doc.observe(lambda event: updates.append(event.update))
    doc.get("body", type=Text).insert(len(str(doc.get("body", type=Text))), text)
    doc.unobserve(subscription)
    for update in updates:
        socket.send_bytes(create_update_message(update))


def _body(doc: Doc) -> str:
    return str(doc.get("body", type=Text))


def _read_until(socket, doc: Doc, expected: str, limit: int = 20) -> None:
    for _ in range(limit):
        if _body(doc) == expected:
            return
        _apply(socket, doc)
    assert _body(doc) == expected


# --- the tests ---------------------------------------------------------------------


def test_two_editors_converge_and_the_observer_cannot_write(stage):
    client, s = stage
    page_id, cookies = s["page_id"], s["cookies"]
    ada, grace = _join(client, page_id, cookies["ada"]), _join(client, page_id, cookies["grace"])
    reader = _join(client, page_id, cookies["reader"], CollabRole.OBSERVER)
    assert ada["seed"] is True and grace["seed"] is False and reader["seed"] is False
    assert ada["page_version"] == 1

    doc_a, doc_g, doc_r = Doc(), Doc(), Doc()
    with (
        _connect(client, page_id, cookies["ada"], ada["session"]) as sock_a,
        _connect(client, page_id, cookies["grace"], grace["session"]) as sock_g,
        _connect(client, page_id, cookies["reader"], reader["session"]) as sock_r,
    ):
        for sock, doc in ((sock_a, doc_a), (sock_g, doc_g), (sock_r, doc_r)):
            _handshake(sock, doc)
        _type(sock_a, doc_a, "hello")
        _read_until(sock_g, doc_g, "hello")
        _type(sock_g, doc_g, " world")
        _read_until(sock_a, doc_a, "hello world")
        _read_until(sock_r, doc_r, "hello world")

        # The observer's update is dropped: never applied, never broadcast.
        _type(sock_r, doc_r, "!!!")
        _type(sock_a, doc_a, ".")
        _read_until(sock_g, doc_g, "hello world.")
        _read_until(sock_a, doc_a, "hello world.")
        assert "!!!" not in _body(doc_g)
    client.portal.call(hub.room(page_id).flush)
    stored = client.portal.call(store.load, page_id)
    assert stored is not None and stored[1] == 1
    resumed = Doc()
    resumed.apply_update(stored[0])
    assert _body(resumed) == "hello world."


def test_seed_grant_passes_on_when_its_holder_leaves(stage):
    client, s = stage
    page_id, cookies = s["page_id"], s["cookies"]
    first = _join(client, page_id, cookies["ada"])
    assert first["seed"] is True
    assert _join(client, page_id, cookies["grace"])["seed"] is False
    with _connect(client, page_id, cookies["ada"], first["session"]) as sock:
        _handshake(sock, Doc())
    # The holder left without seeding: the next editor is granted.
    assert _join(client, page_id, cookies["grace"])["seed"] is True
    # A grant the holder never used lapses on its own too.
    assert _join(client, page_id, cookies["ada"])["seed"] is False
    room = hub.room(page_id)
    room._seed_granted_at -= settings.collab_seed_grant_seconds + 1
    assert _join(client, page_id, cookies["ada"])["seed"] is True


def test_stored_state_resumes_only_at_the_page_version_it_was_written_for(stage):
    client, s = stage
    page_id, cookies = s["page_id"], s["cookies"]
    seeded = Doc()
    seeded.get("body", type=Text).insert(0, "from the store")

    client.portal.call(store.save, page_id, seeded.get_update(), 1)  # matches
    joined = _join(client, page_id, cookies["ada"])
    assert joined["seed"] is False  # a resumed document is not empty
    doc = Doc()
    with _connect(client, page_id, cookies["ada"], joined["session"]) as sock:
        _handshake(sock, doc)
    assert _body(doc) == "from the store"

    client.portal.call(hub.invalidate, page_id)
    client.portal.call(store.save, page_id, seeded.get_update(), 7)  # stale
    joined = _join(client, page_id, cookies["ada"])
    assert joined["seed"] is True  # discarded: the markdown is the truth
    doc = Doc()
    with _connect(client, page_id, cookies["ada"], joined["session"]) as sock:
        _handshake(sock, doc)
    assert _body(doc) == ""
    assert client.portal.call(store.load, page_id) is None


def test_outside_write_is_refused_while_an_editor_is_connected(stage):
    client, s = stage
    page_id, cookies = s["page_id"], s["cookies"]
    joined = _join(client, page_id, cookies["ada"])
    patch = f"{API}/pages/{page_id}"
    grace = {SESSION_COOKIE_NAME: cookies["grace"]}
    with _connect(client, page_id, cookies["ada"], joined["session"]) as sock:
        _handshake(sock, Doc())
        refused = client.patch(patch, json={"body": "over the top"}, cookies=grace)
        assert refused.status_code == 409, refused.text
        assert "being edited live by Ada" in refused.json()["detail"]
        # A title change touches nothing the room holds.
        assert client.patch(patch, json={"title": "Renamed"}, cookies=grace).status_code == 200
        # The room's own save: a stale expected_version is not a conflict.
        saved = client.patch(
            patch,
            json={"body": "from the room", "expected_version": 1, "collab_session": joined["session"]},
            cookies={SESSION_COOKIE_NAME: cookies["ada"]},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["version"] == 3
        assert hub.room(page_id).page_version == 3
    accepted = client.patch(patch, json={"body": "after they left"}, cookies=grace)
    assert accepted.status_code == 200, accepted.text
    # …and that write replaced the room's document: the room is gone with it.
    assert hub.room(page_id) is None


def test_collab_saves_coalesce_into_one_history_row_per_window(stage):
    client, s = stage
    page_id, cookies = s["page_id"], s["cookies"]
    joined = _join(client, page_id, cookies["ada"])
    ada = {SESSION_COOKIE_NAME: cookies["ada"]}
    patch = f"{API}/pages/{page_id}"

    async def rows() -> int:
        engine = create_async_engine(settings.database_url)
        async with async_sessionmaker(engine)() as db:
            count = (
                await db.execute(
                    select(func.count()).select_from(PageVersion).where(PageVersion.page_id == page_id)
                )
            ).scalar_one()
        await engine.dispose()
        return count

    with _connect(client, page_id, cookies["ada"], joined["session"]) as sock:
        _handshake(sock, Doc())
        for body in ("one", "two", "three"):
            response = client.patch(patch, json={"body": body, "collab_session": joined["session"]}, cookies=ada)
            assert response.status_code == 200, response.text
        assert client.portal.call(rows) == 1  # the first opened the window; the rest sat inside it
        response = client.patch(
            patch, json={"body": "done", "collab_session": joined["session"], "final": True}, cookies=ada
        )
        assert response.status_code == 200 and response.json()["version"] == 5
        assert client.portal.call(rows) == 2


def test_who_may_join_and_who_may_connect(stage):
    client, s = stage
    page_id, cookies = s["page_id"], s["cookies"]
    join = f"{API}/collab/pages/{page_id}/join"
    assert client.post(join, json={"role": "editor"}).status_code == 401  # the anonymous Actor never joins
    reader = {SESSION_COOKIE_NAME: cookies["reader"]}
    assert client.post(join, json={"role": "editor"}, cookies=reader).status_code == 403
    observer = client.post(join, json={"role": "observer"}, cookies=reader)
    assert observer.status_code == 200 and observer.json()["role"] == "observer"

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(f"{API}/collab/pages/{page_id}?session={observer.json()['session']}") as sock:
            sock.receive_bytes()
    assert closed.value.code == WS_CLOSE_UNAUTHENTICATED
    # Grace presenting the reader's session: not hers.
    with pytest.raises(WebSocketDisconnect) as closed:
        with _connect(client, page_id, cookies["grace"], observer.json()["session"]) as sock:
            sock.receive_bytes()
    assert closed.value.code == WS_CLOSE_SESSION_UNKNOWN


def test_a_newcomer_learns_every_awareness_state_at_connect(stage):
    """The saver election is over awareness states; a newcomer that only hears
    the others at their next heartbeat elects itself for those seconds. The
    room sends its snapshot at connect AND answers the provider's query."""
    client, s = stage
    page_id, cookies = s["page_id"], s["cookies"]
    ada, grace = _join(client, page_id, cookies["ada"]), _join(client, page_id, cookies["grace"])
    doc_a, doc_g = Doc(), Doc()
    aware_a, aware_g = Awareness(doc_a), Awareness(doc_g)
    with _connect(client, page_id, cookies["ada"], ada["session"]) as sock_a:
        _handshake(sock_a, doc_a)
        aware_a.set_local_state({"user": {"name": "Ada"}, "role": "editor"})
        sock_a.send_bytes(
            create_awareness_message(aware_a.encode_awareness_update([aware_a.client_id]))
        )
        _apply(sock_a, doc_a)  # the room echoes awareness to every client, sender included
        with _connect(client, page_id, cookies["grace"], grace["session"]) as sock_g:
            # Sent unasked at connect: Ada's state, before or after the sync frames.
            seen = False
            for _ in range(6):
                frame = _apply(sock_g, doc_g) if not seen else sock_g.receive_bytes()
                if frame[0] == YMessageType.AWARENESS:
                    aware_g.apply_awareness_update(read_message(frame[1:]), "server")
                    seen = aware_a.client_id in aware_g.states
                    if seen:
                        break
            assert seen, "the snapshot never arrived"
            assert aware_g.states[aware_a.client_id]["user"]["name"] == "Ada"
            # And in answer to the provider's own query (message type 3).
            sock_g.send_bytes(bytes([YClientMessage.QUERY_AWARENESS]))
            kinds = []
            for _ in range(4):  # sync frames may be queued ahead of the answer
                kinds.append(sock_g.receive_bytes()[0])
                if kinds[-1] == YMessageType.AWARENESS:
                    break
            assert YMessageType.AWARENESS in kinds, kinds


async def _reader_permissions(s, permissions):
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine)() as db:
        role = await db.get(Role, s['role_id'])
        role.permissions = [str(p) for p in permissions]
        await db.commit()
    await engine.dispose()


@pytest.mark.parametrize('role', [CollabRole.OBSERVER, CollabRole.EDITOR])
@pytest.mark.parametrize('connected', [False, True])
def test_revoked_page_access_closes_live_and_reused_joins(stage, role, connected):
    client, s = stage
    permissions = [Permission.PAGE_READ, Permission.PAGE_WRITE]
    client.portal.call(_reader_permissions, s, permissions)
    reader = _join(client, s['page_id'], s['cookies']['reader'], role)
    # Keep read access when revoking an editor: a formerly writable join must
    # not silently retain its write role just because the person can still read.
    remaining = [Permission.PAGE_READ] if role == CollabRole.EDITOR else []
    if not connected:
        client.portal.call(_reader_permissions, s, remaining)
        with pytest.raises(WebSocketDisconnect) as closed:
            with _connect(client, s['page_id'], s['cookies']['reader'], reader['session']) as sock:
                sock.receive_bytes()
        assert closed.value.code == WS_CLOSE_SESSION_UNKNOWN
        return

    ada = _join(client, s['page_id'], s['cookies']['ada'])
    doc_a, doc_r = Doc(), Doc()
    with _connect(client, s['page_id'], s['cookies']['ada'], ada['session']) as sock_a:
        _handshake(sock_a, doc_a)
        with _connect(client, s['page_id'], s['cookies']['reader'], reader['session']) as sock_r:
            _handshake(sock_r, doc_r)
            client.portal.call(_reader_permissions, s, remaining)
            if role == CollabRole.EDITOR:
                _type(sock_r, doc_r, 'forbidden edit')
            else:
                _type(sock_a, doc_a, 'new private text')
            with pytest.raises(WebSocketDisconnect) as closed:
                sock_r.receive_bytes()
            assert closed.value.code == WS_CLOSE_SESSION_UNKNOWN
            if role == CollabRole.EDITOR:
                assert 'forbidden edit' not in _body(hub.room(s['page_id']).ydoc)
                _type(sock_a, doc_a, 'allowed')
                _read_until(sock_a, doc_a, 'allowed')


async def _restrict_ancestor(s):
    from radd.modules.access import service as access
    from radd.modules.access.types import Access, GrantSubject
    from radd.modules.pages.page_access import PAGE_RESOURCE
    from radd.modules.pages.schemas import PageUpdate

    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine)() as db:
        parent = await pages_service.create_page(
            db, PageCreate(space_id=s['space_id'], title='Restricted parent'), s['users']['ada']
        )
        await pages_service.update_page(db, s['page_id'], PageUpdate(parent_id=parent.id), s['users']['ada'])
        await access.add_grant(db, PAGE_RESOURCE, str(parent.id), subject_type=GrantSubject.USER,
                               subject_id=s['users']['ada'], access=Access.READ.value, actor_id=s['users']['ada'])
        await db.commit()
    await engine.dispose()


def test_live_reader_loses_access_after_move_under_restricted_ancestor(stage):
    client, s = stage
    reader = _join(client, s['page_id'], s['cookies']['reader'], CollabRole.OBSERVER)
    with _connect(client, s['page_id'], s['cookies']['reader'], reader['session']) as sock:
        _handshake(sock, Doc())
        client.portal.call(_restrict_ancestor, s)
        channel = hub.room(s['page_id']).channels[uuid.UUID(reader['session'])]
        assert client.portal.call(channel._revalidate) is False
        with pytest.raises(WebSocketDisconnect) as closed:
            sock.receive_bytes()
        assert closed.value.code == WS_CLOSE_SESSION_UNKNOWN


def test_idle_reader_is_closed_on_permission_refresh_deadline(stage, monkeypatch):
    monkeypatch.setattr(settings, 'realtime_session_refresh_seconds', 0.1)
    client, s = stage
    reader = _join(client, s['page_id'], s['cookies']['reader'], CollabRole.OBSERVER)
    with _connect(client, s['page_id'], s['cookies']['reader'], reader['session']) as sock:
        _handshake(sock, Doc())
        client.portal.call(_reader_permissions, s, [])
        with pytest.raises(WebSocketDisconnect) as closed:
            sock.receive_bytes()
        assert closed.value.code == WS_CLOSE_SESSION_UNKNOWN
