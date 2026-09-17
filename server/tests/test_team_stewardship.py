"""Steward windows preserve authority and unseen managers during edits."""
from test_team_directory import team_reader_account
import asyncio
import uuid
import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.exceptions import ConflictError
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.auth.types import UserSource
from radd.modules.teams import service as teams
from radd.modules.teams.models import Team, TeamManager


@pytest.mark.parametrize('scope,allowed', [('owner',True),('global',True),('manager',False),('read',False),('delete',False),('project',False)])
async def test_steward_endpoints_follow_owner_global_gate(scope, allowed):
    engine=create_async_engine(settings.database_url)
    async with async_sessionmaker(engine,expire_on_commit=False)() as db:
        prefix=uuid.uuid4().hex
        actor=User(name='Steward actor',email=prefix+'@test.invalid',instance_role='admin')
        target=User(name='Target',email=prefix+'-target@test.invalid');db.add_all([actor,target]);await db.flush()
        team=Team(name=prefix,owner_id=actor.id if scope=='owner' else None);db.add(team);await db.flush()
        if scope=='manager':db.add(TeamManager(team_id=team.id,user_id=actor.id));await db.flush()
        scopes={'global':['team.read']}
        if scope in ('global','owner'):scopes['global'].append('team.update')
        if scope=='delete':scopes['global'].append('team.delete')
        if scope=='project':scopes['projects']={str(uuid.uuid4()):['team.update']}
        _,token=await auth.create_api_token(db,actor,TokenCreate(name='Test',scopes=scopes))
        async def override():yield db
        app=create_app();app.dependency_overrides[get_session]=override
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Authorization':f'Bearer {token}'}) as client:
            path=f'/api/v1/teams/{team.id}'
            for suffix in ('/stewardship','/steward-candidates?purpose=owner','/steward-candidates?purpose=manager'):
                r=await client.get(path+suffix);assert r.status_code==(200 if allowed else 403),r.text
            r=await client.post(path+'/managers',json={'user_id':str(target.id)});assert r.status_code==(204 if allowed else 403),r.text
            r=await client.delete(path+'/managers/'+str(target.id));assert r.status_code==(204 if allowed else 403),r.text
        await db.rollback()
    await engine.dispose()


async def test_steward_pages_candidates_legacy_rows_and_manager_promotion():
    engine=create_async_engine(settings.database_url)
    async with async_sessionmaker(engine,expire_on_commit=False)() as db:
        prefix=uuid.uuid4().hex
        actor=User(name='Owner',email=prefix+'@test.invalid',instance_role='admin')
        managers=[User(name=f'Manager {i:03}',email=f'{prefix}-m{i}@test.invalid') for i in range(126)]
        candidates=[User(name=f'Candidate {i:03}',email=f'{prefix}-c{i}@test.invalid') for i in range(126)]
        inactive=User(name='Candidate inactive',email=prefix+'-inactive@test.invalid',active=False)
        mail=User(name='Candidate mail',email=prefix+'-mail@test.invalid',source=UserSource.EMAIL)
        service=User(name='Candidate service',email=prefix+'-svc@test.invalid',source=UserSource.SERVICE)
        managers[125].active=False
        db.add_all([actor,*managers,*candidates,inactive,mail,service]);await db.flush()
        team=Team(name=prefix,owner_id=actor.id);db.add(team);await db.flush()
        db.add_all([TeamManager(team_id=team.id,user_id=p.id) for p in managers]);await db.flush()
        await team_reader_account(db,actor)
        _,token=await auth.create_api_token(db,actor,TokenCreate(name='Owner',scopes={'global':['team.read','team.update']}))
        async def override():yield db
        app=create_app();app.dependency_overrides[get_session]=override
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Authorization':f'Bearer {token}'}) as client:
            path=f'/api/v1/teams/{team.id}'
            seen=[]
            for offset,count in [(0,50),(50,50),(100,26)]:
                r=await client.get(path+'/stewardship',params={'limit':50,'offset':offset});assert r.status_code==200,r.text
                data=r.json();assert data['total']==126 and len(data['managers'])==count
                assert data['owner']=={'id':str(actor.id),'name':actor.name,'active':True}
                assert all(set(p)=={'id','name','active'} for p in data['managers']);seen+=data['managers']
            assert [p['id'] for p in seen]==[str(p.id) for p in managers] and not seen[-1]['active']
            for offset,count in [(0,50),(50,50),(100,27)]:
                r=await client.get(path+'/steward-candidates',params={'purpose':'manager','q':'  CANDIDATE  ','limit':50,'offset':offset})
                assert r.status_code==200 and r.headers['X-Total-Count']=='127' and len(r.json())==count,r.text
                assert all(set(p)=={'id','name'} for p in r.json())
            r=await client.get(path+'/steward-candidates',params={'purpose':'manager','q':'Manager'});assert r.json()==[]
            r=await client.get(path+'/steward-candidates',params={'purpose':'owner','q':'Manager 124'});assert r.json()[0]['id']==str(managers[124].id)
            r=await client.get(path+'/steward-candidates',params={'purpose':'owner','q':'Manager 125'});assert r.json()==[]
            r=await client.get(path+'/steward-candidates',params={'purpose':'owner','q':'%_'});assert r.json()==[] and r.headers['X-Total-Count']=='0'
            # Legacy/transfer-expanded sets can be reduced one row at a time;
            # no full-set PUT and no accidental removal of off-page managers.
            assert (await client.delete(path+'/managers/'+str(managers[125].id))).status_code==204
            held=set(await teams.list_managers(db,team.id));assert held=={p.id for p in managers[:125]}
            assert (await client.post(path+'/managers',json={'user_id':str(candidates[125].id)})).status_code==409
            assert (await client.post(path+'/managers',json={'user_id':str(managers[124].id)})).status_code==204  # idempotent
            r=await client.post(path+'/transfer',json={'user_id':str(managers[124].id)});assert r.status_code==200,r.text
            assert r.json()['owner_id']==str(managers[124].id)
            held=set(await teams.list_managers(db,team.id));assert actor.id in held and managers[124].id not in held
            # The previous owner is now a delegate, and cannot delegate further.
            assert (await client.get(path+'/stewardship')).status_code==403
            assert (await client.post(path+'/managers',json={'user_id':str(candidates[125].id)})).status_code==403
            for params in ({'purpose':'invalid'},{'purpose':'owner','limit':201},{'purpose':'owner','offset':-1},{'purpose':'owner','q':'x'*201}):
                assert (await client.get(path+'/steward-candidates',params=params)).status_code==422
        await db.rollback()
    await engine.dispose()


async def test_concurrent_manager_additions_do_not_lose_rows_or_exceed_limit():
    engine=create_async_engine(settings.database_url)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    prefix=uuid.uuid4().hex
    async with factory() as db:
        people=[User(name=f'Concurrent {i}',email=f'{prefix}-{i}@test.invalid') for i in range(51)]
        team=Team(name=prefix);db.add_all([team,*people]);await db.flush()
        db.add_all([TeamManager(team_id=team.id,user_id=p.id) for p in people[:49]]);await db.commit()
        team_id=team.id;ids=[p.id for p in people]
    async def add(person_id):
        async with factory() as db:
            try:
                await teams.add_manager(db,team_id,person_id);await db.commit();return True
            except ConflictError:
                await db.rollback();return False
    try:
        assert sorted(await asyncio.gather(add(ids[49]),add(ids[50])))==[False,True]
        async with factory() as db:
            held=set(await teams.list_managers(db,team_id));assert len(held)==50 and set(ids[:49])<=held
    finally:
        async with factory() as db:
            await db.execute(delete(Team).where(Team.id==team_id));await db.execute(delete(User).where(User.id.in_(ids)));await db.commit()
        await engine.dispose()
