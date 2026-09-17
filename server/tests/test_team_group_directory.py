"""Group paging retains nested counts, external edge names and team authority."""
from test_team_directory import team_reader_account
import uuid
import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker,create_async_engine
from radd.app import create_app
from radd.clock import utcnow
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.groups.models import Group,GroupMember,GroupParent
from radd.modules.projects.models import Project
from radd.modules.teams.models import Team,TeamMember,TeamManager
from radd.modules.teams import service as teams

@pytest.mark.parametrize('scope,allowed', [('owner',True),('manager',True),('global',True),('reader',False),('project',False)])
async def test_group_candidates_match_attachment_guards(scope,allowed):
    engine=create_async_engine(settings.database_url)
    async with async_sessionmaker(engine,expire_on_commit=False)() as db:
        prefix=uuid.uuid4().hex
        actor=User(name='Group operator',email=prefix+'@test.invalid',instance_role='admin');db.add(actor);await db.flush()
        team=Team(name=prefix,owner_id=actor.id if scope=='owner' else None)
        group=Group(name=prefix,dn=prefix);db.add_all([team,group]);await db.flush()
        if scope=='manager':db.add(TeamManager(team_id=team.id,user_id=actor.id));await db.flush()
        if scope in ('owner','manager'):await team_reader_account(db,actor)
        scopes={'global':['team.read']}
        if scope in ('global','owner','manager'):scopes['global'].append('team.update')
        if scope=='project':scopes['projects']={str(uuid.uuid4()):['team.update']}
        _,token=await auth.create_api_token(db,actor,TokenCreate(name='Group reader',scopes=scopes))
        async def override():yield db
        app=create_app();app.dependency_overrides[get_session]=override
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Authorization':f'Bearer {token}'}) as client:
            path=f'/api/v1/teams/{team.id}'
            r=await client.get(path+'/group-candidates',params={'q':prefix,'limit':50});assert r.status_code==(200 if allowed else 403),r.text
            r=await client.post(path+'/groups',json={'group_id':str(group.id)});assert r.status_code==(201 if allowed else 403),r.text
            if allowed:
                r=await client.get(path+'/group-candidates',params={'q':prefix,'limit':50});assert r.json()==[] and r.headers['X-Total-Count']=='0'
            r=await client.get(path+'/groups',params={'limit':50});assert r.status_code==200 and len(r.json())==int(allowed)
            # Sync is deliberately global: it reconciles directory-owned groups
            # that may affect other teams, rather than editing a local attachment.
            if scope!='global':assert (await client.post(path+'/directory-sync')).status_code==403
        await db.rollback()
    await engine.dispose()

async def test_group_windows_counts_and_cross_page_nesting_names():
    engine=create_async_engine(settings.database_url)
    async with async_sessionmaker(engine,expire_on_commit=False)() as db:
        prefix=uuid.uuid4().hex
        actor=User(name='Directory owner',email=prefix+'@test.invalid',instance_role='admin');db.add(actor);await db.flush()
        held=[Group(name=f'{prefix} held {i:03}',dn=f'{prefix}-held-{i}') for i in range(126)]
        candidates=[Group(name=f'{prefix} candidate {i:03}',dn=f'{prefix}-candidate-{i}') for i in range(126)]
        child=Group(name=prefix+' child',dn=prefix+'-child')
        team=Team(name=prefix,owner_id=actor.id);held[125].directory_missing_since=utcnow()
        db.add_all([*held,*candidates,child,team]);await db.flush()
        db.add_all([TeamMember(team_id=team.id,group_id=g.id) for g in held])
        db.add(GroupParent(parent_id=candidates[125].id,child_id=child.id));db.add(GroupMember(group_id=child.id,user_id=actor.id));await db.flush()
        _,token=await auth.create_api_token(db,actor,TokenCreate(name='Owner',scopes={'global':['team.read','team.update']}))
        _,admin=await auth.create_api_token(db,actor,TokenCreate(name='Admin',scopes=None))
        async def override():yield db
        app=create_app();app.dependency_overrides[get_session]=override
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Authorization':f'Bearer {token}'}) as client:
            path=f'/api/v1/teams/{team.id}'
            for suffix,term in [('/groups','held'),('/group-candidates','candidate')]:
                seen=[]
                for offset,count in [(0,50),(50,50),(100,26)]:
                    sql=[]
                    def record(conn,cursor,statement,parameters,context,executemany):sql.append(statement)
                    event.listen(engine.sync_engine,'before_cursor_execute',record)
                    try:r=await client.get(path+suffix,params={'q':'  '+prefix.upper()+' '+term.upper()+'  ','limit':50,'offset':offset})
                    finally:event.remove(engine.sync_engine,'before_cursor_execute',record)
                    assert r.status_code==200,r.text
                    assert r.headers['X-Total-Count']=='126' and len(r.json())==count
                    seen.extend(g['group_id'] for g in r.json())
                    if suffix.endswith('candidates'):assert sum('WITH RECURSIVE group_member_reach' in stmt for stmt in sql)==1
                assert len(set(seen))==126
            r=await client.get(path+'/group-candidates',params={'q':candidates[125].dn,'limit':50});assert len(r.json())==1
            assert r.json()[0]['direct_member_count']==0 and r.json()[0]['transitive_member_count']==1
            r=await client.get(path+'/groups',params={'q':held[125].dn,'limit':50});assert r.json()[0]['directory_missing_since']
            r=await client.get(path+'/group-candidates',params={'q':prefix+' held','limit':50});assert r.json()==[]
            for suffix in ('/groups','/group-candidates'):
                for params in ({'limit':0},{'offset':-1},{'q':'x'*201}):assert (await client.get(path+suffix,params=params)).status_code==422
                r=await client.get(path+suffix,params={'q':'%_','limit':50});assert r.json()==[] and r.headers['X-Total-Count']=='0'
            # Global group reads retain the existing readable-project floor.
            db.add(Project(key='G'+uuid.uuid4().hex[:7],name=prefix));await db.flush();db.info.clear()
            # A filtered global group page must resolve its off-page child name.
            r=await client.get('/api/v1/groups',params={'q':candidates[125].name,'limit':1},headers={'Authorization':f'Bearer {admin}'})
            assert r.status_code==200,r.text
            assert r.json()[0]['child_names']==[child.name] and r.json()[0]['transitive_member_count']==1
            r=await client.get('/api/v1/groups',params={'q':child.name,'limit':1},headers={'Authorization':f'Bearer {admin}'})
            assert r.json()[0]['parent_names']==[candidates[125].name]
            assert (await client.post(path+'/groups',json={'group_id':str(candidates[125].id)})).status_code==201
            r=await client.get(path+'/members',params={'limit':50});assert r.json()[0]['user_id']==str(actor.id)
            assert (await client.delete(path+'/groups/'+str(candidates[125].id))).status_code==204
            r=await client.get(path+'/members',params={'limit':50});assert r.json()==[]
        assert len(await teams.team_groups(db,team.id))==126  # sync's internal full read is intact
        await db.rollback()
    await engine.dispose()
