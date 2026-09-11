"""Space access windows and reference choices preserve names, policy and scope."""
import uuid
from datetime import timedelta
import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from radd.app import create_app
from radd.clock import utcnow
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import roles as role_service, service as auth
from radd.modules.auth.models import GlobalRoleGrant, Role, User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.auth.types import BuiltinRoleKey
from radd.modules.groups.service import Group
from radd.modules.pages.models import PageSpace
from radd.modules.projects.models import Project
from radd.modules.teams.models import Team


@pytest.fixture
async def access_world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        prefix = uuid.uuid4().hex[:8]
        baseline = await role_service.role_by_key(db, BuiltinRoleKey.BASELINE); baseline.permissions = []
        admin = User(name="Admin", email=prefix+'admin@test.invalid', instance_role='admin')
        reader = User(name="Wiki reader", email=prefix+'reader@test.invalid')
        read_role = Role(key=prefix+'reader', name='Wiki read', permissions=['page.read'])
        space = PageSpace(name=prefix+'space', slug=prefix+'space')
        hidden = PageSpace(name=prefix+'hidden', slug=prefix+'hidden')
        project = Project(key='P'+prefix.upper(), name='Membership floor')
        roles = [Role(key=prefix+str(i), name=f'{prefix} role {i:03}', permissions=[]) for i in range(126)]
        people = [User(name=f'{prefix} person {i:03}', email=f'{prefix}-{i}@test.invalid') for i in range(126)]
        people[0].name += ' %_'; people[3].active = False; people[6].source = 'service'; people[9].source = 'email'
        teams = [Team(name=f'{prefix} team {i:03}') for i in range(126)]
        groups = [Group(name=f'{prefix} group {i:03}', dn=f'CN={prefix}-{i},OU=Groups') for i in range(126)]
        db.add_all([admin,reader,read_role,space,hidden,project,*roles,*people,*teams,*groups]);await db.flush()
        start = utcnow()-timedelta(days=1)
        grants = [GlobalRoleGrant(role_id=roles[i].id, space_id=space.id,
                    user_id=people[i].id if i%3==0 else None, team_id=teams[i].id if i%3==1 else None,
                    group_id=groups[i].id if i%3==2 else None, created_at=start,
                    expires_at=start if i==124 else None) for i in range(125)]
        grants.append(GlobalRoleGrant(role_id=read_role.id, space_id=space.id, user_id=reader.id, created_at=start))
        db.add_all([*grants,GlobalRoleGrant(role_id=roles[0].id,space_id=hidden.id,user_id=admin.id),GlobalRoleGrant(role_id=roles[1].id,user_id=admin.id)])
        await db.flush();db.info.clear()
        admin_cookie=await auth.create_session(db,admin);reader_cookie=await auth.create_session(db,reader)
        app=create_app()
        async def override():yield db
        app.dependency_overrides[get_session]=override
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',cookies={'radd_session':admin_cookie}) as client:
            yield db,client,space,hidden,grants,roles,people,teams,groups,reader_cookie,engine,prefix
        await db.rollback()
    await engine.dispose()


async def test_space_access_pages_names_expiry_and_window_hydration(access_world):
    db,client,space,_,grants,roles,people,teams,groups,_,engine,_=access_world
    seen=[];statements=[]
    def capture(conn,cursor,statement,parameters,context,executemany):statements.append((statement,parameters))
    event.listen(engine.sync_engine,'before_cursor_execute',capture)
    try:
        for offset,count in [(0,50),(50,50),(100,26)]:
            response=await client.get(f'/api/v1/role-grants/by-space/{space.id}',params={'limit':50,'offset':offset})
            assert response.status_code==200 and response.headers['X-Total-Count']=='126'
            rows=response.json();assert len(rows)==count;seen.extend(rows)
        assert [row['id'] for row in seen]==[str(g.id) for g in sorted(grants,key=lambda g:g.id)]
        names={str(u.id):u.name for u in people if u.source!='email'}|{str(t.id):t.name for t in teams}|{str(g.id):g.name for g in groups}
        for row in seen:
            subject=row['user_id'] or row['team_id'] or row['group_id']
            if subject in names:assert row['subject_name']==names[subject]
            assert 'permissions' not in row and 'email' not in row and 'password_hash' not in row
        assert next(r for r in seen if r['user_id']==str(people[3].id))['subject_active'] is False
        assert next(r for r in seen if r['user_id']==str(people[9].id))['subject_name'] is None
        assert next(r for r in seen if r['id']==str(grants[124].id))['expired'] is True
        for sql,params in statements:
            if sql.startswith(('SELECT users.id, users.name, users.active','SELECT teams.id, teams.name','SELECT groups.id, groups.name','SELECT roles.id, roles.name')):
                assert 'WHERE' in sql and ' IN (' in sql
                assert len(params)<=50
        assert any(sql.startswith('SELECT users.id, users.name, users.active') for sql,_ in statements)
    finally:event.remove(engine.sync_engine,'before_cursor_execute',capture)
    response=await client.get(f'/api/v1/role-grants/by-space/{space.id}',params={'q':'%_'})
    assert response.headers['X-Total-Count']=='1' and response.json()[0]['user_id']==str(people[0].id)
    # Original complete grant readers retain the full set.
    assert len((await client.get('/api/v1/role-grants',params={'space_id':str(space.id)})).json())==126


async def test_hidden_catalog_names_do_not_leak_through_rows_or_search(access_world):
    _,client,space,hidden,_,roles,people,teams,groups,cookie,_,_=access_world
    client.cookies.clear();client.cookies.set('radd_session',cookie)
    base=f'/api/v1/role-grants/by-space/{space.id}'
    response=await client.get(base,params={'limit':200});assert response.status_code==200
    for row in response.json():
        assert row['role_name'] is None
        if row['team_id'] or row['group_id']:assert row['subject_name'] is None
    for secret in [roles[2].name,teams[1].name,groups[2].name,people[9].name]:
        response=await client.get(base,params={'q':secret});assert response.json()==[] and response.headers['X-Total-Count']=='0'
    assert (await client.get(f'/api/v1/role-grants/by-space/{hidden.id}')).status_code==403
    assert (await client.get('/api/v1/teams/directory/options')).json()==[]
    assert (await client.get('/api/v1/groups/options')).status_code==403
    assert (await client.get('/api/v1/roles/options')).json()==[]


async def test_reference_choices_page_stably_and_keep_wire_identity(access_world):
    _,client,_,_,_,roles,people,teams,groups,_,_,prefix=access_world
    for route,rows,noun in [('roles/options',roles,'role'),('teams/directory/options',teams,'team'),('groups/options',groups,'group'),('users/directory/options',[u for u in people if u.source!='email'],'person')]:
        seen=[]
        for offset in [0,50,100]:
            response=await client.get('/api/v1/'+route,params={'q':prefix+' '+noun,'offset':offset,'limit':50})
            assert response.status_code==200 and response.headers['X-Total-Count']==str(len(rows))
            window=response.json();assert len(window)<=50;assert all(set(r)=={'value','label','hint'} for r in window);seen.extend(window)
        assert [r['value'] for r in seen]==[str(r.id) for r in rows]
        direct=await client.get('/api/v1/'+route,params={'value':str(rows[-1].id),'limit':1});assert len(direct.json())==1 and direct.json()[0]['value']==str(rows[-1].id)
    inactive=(await client.get('/api/v1/users/directory/options',params={'value':str(people[3].id)})).json();assert inactive[0]['hint']=='Inactive account'
    service=(await client.get('/api/v1/users/directory/options',params={'value':str(people[6].id)})).json();assert service[0]['hint']=='Service account'
    assert (await client.get('/api/v1/users/directory/options',params={'value':str(people[9].id)})).json()==[]
    assert (await client.get('/api/v1/users/directory/options',params={'q':people[0].email})).json()==[]
    # Automation team options still store names, not IDs.
    assert (await client.get('/api/v1/teams/options',params={'value':teams[0].name})).json()[0]['value']==teams[0].name


async def test_scoped_admin_key_is_intersected_before_names_and_mutations(access_world):
    db,client,space,_,grants,_,_,_,_,_,_,prefix=access_world
    key_admin=User(name='Key admin',email=prefix+'key@test.invalid',instance_role='admin');db.add(key_admin);await db.flush()
    _,key=await auth.create_api_token(db,key_admin,TokenCreate(name='read only',scopes={'global':['page.read']}))
    client.cookies.clear();client.headers['Authorization']='Bearer '+key
    response=await client.get(f'/api/v1/role-grants/by-space/{space.id}');assert response.status_code==200
    assert all(r['role_name'] is None and (r['user_id'] or r['subject_name'] is None) for r in response.json())
    assert (await client.delete('/api/v1/role-grants/'+str(grants[0].id))).status_code==403
    assert (await client.get('/api/v1/teams/directory/options')).json()==[]
    assert (await client.get('/api/v1/groups/options')).status_code==403
    # An empty key has no space-read authority at all.
    other=User(name='Empty key',email=prefix+'empty@test.invalid',instance_role='admin');db.add(other);await db.flush()
    _,empty=await auth.create_api_token(db,other,TokenCreate(name='empty',scopes={}))
    response=await client.get(f'/api/v1/role-grants/by-space/{space.id}',headers={'Authorization':'Bearer '+empty});assert response.status_code==403


async def test_directory_bounds_and_individual_grant_mutations(access_world):
    _,client,space,_,grants,roles,people,teams,groups,_,_,_=access_world
    for route in [f'role-grants/by-space/{space.id}','users/directory/options','teams/directory/options','groups/options']:
        for params in [{'limit':0},{'limit':201},{'offset':-1},{'q':'x'*201}]:assert (await client.get('/api/v1/'+route,params=params)).status_code==422
    original={str(g.id) for g in grants}
    for kind,subject in [('user_id',people[-1]),('team_id',teams[-1]),('group_id',groups[-1])]:
        response=await client.post('/api/v1/role-grants',json={'role_id':str(roles[-1].id),kind:str(subject.id),'space_ids':[str(space.id)]})
        assert response.status_code==201
        created=response.json()[0];assert created[kind]==str(subject.id) and created['space_id']==str(space.id) and created['project_id'] is None
        assert (await client.delete('/api/v1/role-grants/'+created['id'])).status_code==204
    assert {row['id'] for row in (await client.get('/api/v1/role-grants',params={'space_id':str(space.id)})).json()}==original
