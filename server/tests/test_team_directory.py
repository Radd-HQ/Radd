"""Paged team reads must match mutation scope and hydrate a window in one batch."""
import uuid
import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker,create_async_engine
from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.projects.models import Project
from radd.modules.teams.models import Team,TeamManager


@pytest.mark.parametrize('scope,manage,delete', [('global',True,True),('project',False,False),('owner',False,False),('manager',False,False),('delete',False,True)])
async def test_team_capabilities_match_global_write_guards(scope,manage,delete):
    engine=create_async_engine(settings.database_url)
    async with async_sessionmaker(engine,expire_on_commit=False)() as db:
        prefix='team-'+uuid.uuid4().hex[:7]
        actor=User(name='Scoped actor',email=prefix+'@test.invalid',instance_role='admin')
        project=Project(key='TD'+uuid.uuid4().hex[:6],name='Scoped project')
        db.add_all([actor,project]);await db.flush()
        row=Team(name=prefix,owner_id=actor.id if scope=='owner' else None);db.add(row);await db.flush()
        if scope=='manager':db.add(TeamManager(team_id=row.id,user_id=actor.id));await db.flush()
        grants={'global':['team.read']}
        if scope=='global':grants['global']+=['team.update','team.delete']
        if scope=='delete':grants['global']+=['team.delete']
        if scope=='project':grants['projects']={str(project.id):['item.read','team.update','team.delete']}
        _,token=await auth.create_api_token(db,actor,TokenCreate(name='Scoped actor',scopes=grants))
        async def override():yield db
        app=create_app();app.dependency_overrides[get_session]=override
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Authorization':f'Bearer {token}'}) as client:
            rows=await client.get('/api/v1/teams',params={'q':prefix,'limit':50});assert rows.status_code==200
            data=rows.json()[0]
            assert (data['can_manage'],data['can_delete'])==(manage,delete)
            detail=await client.get('/api/v1/teams/'+str(row.id));assert detail.status_code==200 and detail.json()==data
            updated=await client.patch('/api/v1/teams/'+str(row.id),json={'name':prefix+' edited'})
            assert updated.status_code==(200 if manage else 403),updated.text
            removed=await client.delete('/api/v1/teams/'+str(row.id))
            assert removed.status_code==(204 if delete else 403),removed.text
        await db.rollback()
    await engine.dispose()


async def test_team_windows_search_count_and_batch_hydration():
    engine=create_async_engine(settings.database_url)
    async with async_sessionmaker(engine,expire_on_commit=False)() as db:
        prefix='team-'+uuid.uuid4().hex[:7]
        actor=User(name='Directory reader',email=prefix+'@test.invalid',instance_role='admin');db.add(actor);await db.flush()
        _,token=await auth.create_api_token(db,actor,TokenCreate(name='Reader',scopes={'global':['team.read']}))
        _,empty=await auth.create_api_token(db,actor,TokenCreate(name='Empty',scopes={}))
        rows=[Team(name=f'{prefix} {i:03}') for i in range(126)];db.add_all(rows);await db.flush()
        db.add_all([TeamManager(team_id=row.id,user_id=actor.id) for row in rows]);await db.flush()
        async def override():yield db
        app=create_app();app.dependency_overrides[get_session]=override
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Authorization':f'Bearer {token}'}) as client:
            seen=[]
            for offset,count in [(0,50),(50,50),(100,26)]:
                sql=[]
                def record(conn,cursor,statement,parameters,context,executemany):sql.append(statement)
                event.listen(engine.sync_engine,'before_cursor_execute',record)
                try:r=await client.get('/api/v1/teams',params={'q':'  '+prefix.upper()+'  ','limit':50,'offset':offset})
                finally:event.remove(engine.sync_engine,'before_cursor_execute',record)
                assert r.status_code==200 and len(r.json())==count,r.text
                assert r.headers['X-Total-Count']=='126'
                assert sum('FROM team_managers' in stmt for stmt in sql)==1,sql
                assert not any('projects.next_number' in stmt for stmt in sql)
                assert all(row['managers']==[str(actor.id)] and not row['can_manage'] and not row['can_delete'] for row in r.json())
                seen.extend(row['id'] for row in r.json())
            assert len(set(seen))==126
            r=await client.get('/api/v1/teams',params={'q':prefix+' 125','limit':1});assert r.headers['X-Total-Count']=='1'
            literal=Team(name=prefix+' %_');db.add(literal);await db.flush()
            r=await client.get('/api/v1/teams',params={'q':'%_','limit':50});assert r.headers['X-Total-Count']=='1' and r.json()[0]['id']==str(literal.id)
            r=await client.get('/api/v1/teams',params={'q':prefix+' missing','limit':50});assert r.json()==[] and r.headers['X-Total-Count']=='0'
            for params in ({'limit':0},{'offset':-1},{'q':'x'*201}):assert (await client.get('/api/v1/teams',params=params)).status_code==422
            db.info.clear()
            r=await client.get('/api/v1/teams',params={'limit':50},headers={'Authorization':f'Bearer {empty}'})
            assert r.json()==[] and r.headers['X-Total-Count']=='0'
            r=await client.get('/api/v1/teams/'+str(rows[125].id),headers={'Authorization':f'Bearer {empty}'})
            assert r.status_code==403
        await db.rollback()
    await engine.dispose()


async def team_reader_account(db, actor):
    """Real team reader with intrinsic stewardship; key write scope grants no role."""
    from radd.modules.auth.models import Role, GlobalRoleGrant
    actor.instance_role = "member"
    role = Role(key="team-reader-" + uuid.uuid4().hex, name="Team reader", permissions=["team.read"])
    db.add(role)
    await db.flush()
    db.add(GlobalRoleGrant(role_id=role.id, user_id=actor.id))
    await db.flush()
