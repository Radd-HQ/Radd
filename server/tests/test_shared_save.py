"""Sharing drafts must commit all edits together and preserve other policy rows."""

import asyncio
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.clock import utcnow
from radd.config import settings
from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.access import service as grants
from radd.modules.access.router import create_grant
from radd.modules.access.schemas import AccessGrantCreate
from radd.modules.access.types import GrantEffect, GrantSubject
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.auth.types import SESSION_COOKIE_NAME
from radd.modules.dashboards import service as dashboards
from radd.modules.dashboards.schemas import DashboardCreate, DashboardTransfer
from radd.modules.events.models import Event
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.views import service as views
from radd.modules.views.schemas import ViewCreate, ViewTransfer


@pytest.fixture(params=['view', 'dashboard'])
async def world(request):
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        owner, peer, other, inactive = [User(name=name, email=f'{uuid.uuid4()}@test.invalid',
                                           instance_role='admin')
                                       for name in ['Owner', 'Peer', 'Other', 'Inactive']]
        inactive.active = False
        db.add_all([owner, peer, other, inactive])
        await db.flush()
        project = await projects.create_project(db, ProjectCreate(key='TX'+uuid.uuid4().hex[:6], name='Sharing'), actor_id=owner.id)
        kind = request.param
        if kind == 'view':
            resource = await views.create_view(db, ViewCreate(name='Original', view_type='list', project_id=project.id), actor=owner)
        else:
            resource = await dashboards.create_dashboard(db, DashboardCreate(name='Original'), actor=owner)
        yield db, engine, kind, resource, owner, peer, other, inactive
        await db.rollback()
    await engine.dispose()


def payload(resource, **parts):
    return dict(expected_owner_id=str(resource.owner_id), expected_global_access=resource.global_access, **parts)


def change(row, access):
    return dict(id=str(row.id), expected_access=row.access, expected_effect=row.effect,
                expected_expires_at=row.expires_at.isoformat()+'Z' if row.expires_at else None,
                access=access)


async def grant(db, kind, resource, user, level, **extra):
    return await grants.add_grant(db, kind, str(resource.id), subject_type=GrantSubject.USER,
                                  subject_id=user.id, access=level, **extra)


async def client_for(db, actor):
    app = create_app()
    async def override():
        db.info.clear()  # match a fresh request session, including authorization memoization
        yield db
    app.dependency_overrides[get_session] = override
    cookie = await auth.create_session(db, actor)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                             cookies={SESSION_COOKIE_NAME: cookie})


async def test_late_transfer_refusal_rolls_back_definition_grants_and_events(world):
    db, _, kind, resource, owner, peer, other, inactive = world
    saved = await grant(db, kind, resource, peer, 'viewer', expires_at=utcnow()+timedelta(days=1))
    saved_id, owner_id = saved.id, owner.id
    body = payload(resource, definition={'name': 'Must roll back'}, sharing={'global_access': 'viewer'},
        grants={'changes': [change(saved, 'editor')], 'additions': [dict(subject_type='user', subject_id=str(other.id), access='viewer')]},
        transfer_to=str(inactive.id))
    async with await client_for(db, owner) as client:
        before = await db.scalar(select(func.count()).select_from(Event).where(Event.actor_id == owner_id))
        response = await client.post(f'/api/v1/{kind}s/{resource.id}/save', json=body)
        assert response.status_code == 409, response.text
        # The override deliberately does not roll the request back: the owned
        # savepoint must protect even an outer caller that catches the refusal.
        model = await (views.get_view(db, resource.id) if kind == 'view' else dashboards.get_dashboard(db, resource.id))
        assert model.name == 'Original' and model.global_access is None and model.owner_id == owner_id
        rows = await grants.grants_for_resources(db, kind, [str(resource.id)], include_expired=True)
        assert [(r.id, r.access) for r in rows[str(resource.id)]] == [(saved_id, 'viewer')]
        assert await db.scalar(select(func.count()).select_from(Event).where(Event.actor_id == owner_id)) == before


async def test_level_edit_preserves_identity_expiry_and_unmentioned_denies(world):
    db, _, kind, resource, owner, peer, other, _ = world
    expiry = utcnow()+timedelta(days=1)
    edited = await grant(db, kind, resource, peer, 'viewer', expires_at=expiry)
    deny = await grant(db, kind, resource, other, 'owner', effect=GrantEffect.DENY)
    expired = await grant(db, kind, resource, other, 'viewer', expires_at=utcnow()-timedelta(days=1))
    body = payload(resource, grants={'changes': [change(edited, 'editor')]})
    original_id = edited.id
    async with await client_for(db, owner) as client:
        response = await client.post(f'/api/v1/{kind}s/{resource.id}/save', json=body)
        assert response.status_code == 200, response.text
        rows = await grants.grants_for_resources(db, kind, [str(resource.id)], include_expired=True)
        by_id = {r.id: r for r in rows[str(resource.id)]}
        assert len(by_id) == 3 and by_id[original_id].access == 'editor'
        assert by_id[original_id].expires_at == expiry
        assert by_id[deny.id].effect == 'deny' and by_id[expired.id].expires_at < utcnow()
        # A stale edit is refused and cannot partially change the definition.
        body['definition'] = {'name': 'Stale'}
        response = await client.post(f'/api/v1/{kind}s/{resource.id}/save', json=body)
        assert response.status_code == 409, response.text
        model = await (views.get_view(db, resource.id) if kind == 'view' else dashboards.get_dashboard(db, resource.id))
        assert model.name == 'Original'


async def test_coowner_can_revoke_self_and_transfer_in_one_save(world):
    db, _, kind, resource, owner, peer, other, _ = world
    coowner = await grant(db, kind, resource, peer, 'owner')
    owner_id, target_id, coowner_id = owner.id, other.id, coowner.id
    body = payload(resource, grants={'changes': [change(coowner, None)]}, transfer_to=str(target_id))
    async with await client_for(db, peer) as client:
        response = await client.post(f'/api/v1/{kind}s/{resource.id}/save', json=body)
        assert response.status_code == 200, response.text
        assert response.json()['owner_id'] == str(target_id)
        rows = await grants.grants_for_resources(db, kind, [str(resource.id)], include_expired=True)
        assert coowner_id not in [r.id for r in rows[str(resource.id)]]
        assert any(r.subject_id == owner_id and r.access == 'editor' for r in rows[str(resource.id)])


async def test_foreign_grant_and_empty_credential_cannot_mutate(world):
    db, _, kind, resource, owner, peer, _, _ = world
    saved = await grant(db, kind, resource, peer, 'viewer')
    foreign = change(saved, None)
    foreign['id'] = str(uuid.uuid4())
    async with await client_for(db, owner) as client:
        response = await client.post(f'/api/v1/{kind}s/{resource.id}/save', json=payload(resource,
            sharing={'global_access': 'viewer'}, grants={'changes': [foreign]}))
        assert response.status_code == 409, response.text
        _, token = await auth.create_api_token(db, owner, TokenCreate(name='Empty key', scopes={}))
        client.cookies.clear()
        client.headers['Authorization'] = 'Bearer '+token
        for method, path, body in [
            ('POST', f'/{kind}s/{resource.id}/save', payload(resource, grants={'changes': [change(saved, None)]})),
            ('PUT', f'/{kind}s/{resource.id}/sharing', {'global_access': None}),
            ('DELETE', f'/grants/{saved.id}', None),
        ]:
            response = await client.request(method, '/api/v1'+path, json=body)
            assert response.status_code == 403, response.text


async def test_legacy_transfer_serializes_and_rechecks_generic_grant_writer(world):
    db, engine, kind, resource, owner, peer, other, _ = world
    owner_id, peer_id, other_id = owner.id, peer.id, other.id
    await db.commit()
    async with async_sessionmaker(engine, expire_on_commit=False)() as first, async_sessionmaker(engine, expire_on_commit=False)() as second:
        first_owner = await first.get(User, owner_id)
        second_owner = await second.get(User, owner_id)
        # Prime the identity map before ownership changes: locking must refresh it.
        await (views.get_view(second, resource.id) if kind == 'view' else dashboards.get_dashboard(second, resource.id))
        if kind == 'view':
            await views.transfer_ownership(first, resource.id, ViewTransfer(user_id=peer_id), first_owner)
        else:
            await dashboards.transfer_ownership(first, resource.id, DashboardTransfer(user_id=peer_id), first_owner)
        pending = asyncio.create_task(create_grant(AccessGrantCreate(resource_type=kind,
            resource_id=str(resource.id), subject_type='user', subject_id=other_id, access='owner'), second, second_owner))
        try:
            await asyncio.sleep(0.05)
            assert not pending.done(), 'grant authorization must wait for the ownership transaction'
            await first.commit()
            with pytest.raises(ForbiddenError):
                await asyncio.wait_for(pending, 5)
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await second.rollback()
    # Keep only the disposable database affected by this committed concurrency fixture.


async def test_lean_reads_bound_grant_hydration_and_match_legacy_policy(world):
    from sqlalchemy import event
    db, engine, kind, resource, owner, peer, other, _ = world
    people = [User(name=f'Recipient {i:03}', email=f'{uuid.uuid4()}@test.invalid') for i in range(126)]
    db.add_all(people)
    await db.flush()
    db.add_all([grants.AccessGrant(resource_type=kind, resource_id=str(resource.id),
        subject_type='user', subject_id=person.id, access='viewer', effect='allow') for person in people])
    await grant(db, kind, resource, peer, 'owner')
    await grant(db, kind, resource, other, 'owner', effect=GrantEffect.DENY)
    for actor in [owner, peer]:
        async with await client_for(db, actor) as client:
            path = f'/api/v1/{kind}s/{resource.id}'
            legacy = await client.get(path)
            assert legacy.status_code == 200 and len(legacy.json()['shares']) == 127
            statements = []
            def capture(_conn, _cursor, statement, _parameters, _context, _many):
                statements.append(statement)
            event.listen(engine.sync_engine, 'before_cursor_execute', capture)
            try:
                lean = await client.get(path, params={'include_shares': 'false'})
                listing = await client.get(f'/api/v1/{kind}s', params={'include_shares': 'false', 'limit': 50, 'q': resource.name, **({'project_id': str(resource.project_id)} if kind == 'view' else {})})
            finally:
                event.remove(engine.sync_engine, 'before_cursor_execute', capture)
            expected = legacy.json() | {'shares': []}
            assert lean.status_code == 200 and lean.json() == expected
            assert next(row for row in listing.json() if row['id'] == str(resource.id)) == expected
            assert all('access_grants.created_at' not in stmt for stmt in statements), 'lean reads must not materialize grant rows'
            assert any('EXISTS' in stmt and 'access_grants' in stmt for stmt in statements), 'real SQL policy projection exercised'


async def test_concurrent_draft_additions_preserve_both_recipients(world):
    from radd.modules.views.schemas import ViewSave
    from radd.modules.dashboards.schemas import DashboardSave
    db, engine, kind, resource, owner, peer, other, _ = world
    owner_id, recipient_ids = owner.id, [peer.id, other.id]
    await db.commit()
    save = views.save_view if kind == 'view' else dashboards.save_dashboard
    schema = ViewSave if kind == 'view' else DashboardSave
    async with async_sessionmaker(engine, expire_on_commit=False)() as first, async_sessionmaker(engine, expire_on_commit=False)() as second:
        actors = [await first.get(User, owner_id), await second.get(User, owner_id)]
        bodies = [schema(**payload(resource, grants={'additions': [dict(subject_type='user', subject_id=str(id), access='viewer')]})) for id in recipient_ids]
        await save(first, resource.id, bodies[0], actor=actors[0])
        pending = asyncio.create_task(save(second, resource.id, bodies[1], actor=actors[1]))
        try:
            await asyncio.sleep(0.05)
            assert not pending.done()
            await first.commit()
            await asyncio.wait_for(pending, 5)
            await second.commit()
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
    rows = await grants.grants_for_resources(db, kind, [str(resource.id)])
    assert {row.subject_id for row in rows[str(resource.id)]} == set(recipient_ids)
