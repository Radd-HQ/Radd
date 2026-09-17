"""Notification choices filter targets and existing subscriptions before paging."""
import uuid

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import roles, service as auth
from radd.modules.auth.models import GlobalRoleGrant, Role, User
from radd.modules.auth.types import BuiltinRoleKey
from radd.modules.notify.models import NotificationRule
from radd.modules.pages.models import PageSpace
from radd.modules.projects.models import Project
from radd.modules.teams.models import Team


@pytest.fixture
async def world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        prefix = uuid.uuid4().hex[:8]
        baseline = await roles.role_by_key(db, BuiltinRoleKey.BASELINE)
        baseline.permissions = []
        admin = User(name='Admin', email=prefix+'admin@test.invalid', instance_role='admin')
        reader = User(name='Reader', email=prefix+'reader@test.invalid')
        role = Role(key=prefix, name='Reader', permissions=['item.read', 'page.read'])
        projects = [Project(key='P'+prefix[:5].upper()+str(i), name=f'{prefix} project {i:03}') for i in range(176)]
        spaces = [PageSpace(slug=prefix+str(i), name=f'{prefix} space {i:03}') for i in range(176)]
        teams = [Team(name=f'{prefix} team {i:03}') for i in range(176)]
        projects[-1].name += ' %_';spaces[-1].name += ' %_';teams[-1].name += ' %_'
        db.add_all([admin, reader, role, *projects, *spaces, *teams]);await db.flush()
        db.add_all([GlobalRoleGrant(user_id=reader.id, role_id=role.id, project_id=projects[-1].id),
                    GlobalRoleGrant(user_id=reader.id, role_id=role.id, space_id=spaces[-1].id)])
        for scope, entries in [('project', projects), ('space', spaces), ('team', teams)]:
            db.add_all([NotificationRule(user_id=admin.id, scope=scope, scope_id=row.id,
                                       channels={'page_created' if scope=='space' else 'created':'inbox'}) for row in entries[:50]])
        await db.flush();db.info.clear()
        cookie=await auth.create_session(db, admin);reader_cookie=await auth.create_session(db, reader)
        app=create_app()
        async def override():yield db
        app.dependency_overrides[get_session]=override
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',cookies={'radd_session':cookie}) as client:
            yield db, client, admin, reader, reader_cookie, projects, spaces, teams, prefix, engine
        await db.rollback()
    await engine.dispose()


async def test_candidates_exclude_before_count_page_and_search(world):
    _,client,_,_,_,projects,spaces,teams,prefix,_=world
    for scope,entries in [('project',projects),('space',spaces),('team',teams)]:
        seen=[]
        for offset,count in [(0,50),(50,50),(100,26)]:
            r=await client.get('/api/v1/notifications/subscription-options',params={'scope':scope,'q':prefix,'limit':50,'offset':offset})
            assert r.status_code==200,r.text
            assert r.headers['X-Total-Count']=='126'
            assert len(r.json())==count
            assert all(set(row)=={'value','label','hint'} for row in r.json())
            seen.extend(row['value'] for row in r.json())
        assert seen==[str(row.id) for row in entries[50:]]
        r=await client.get('/api/v1/notifications/subscription-options',params={'scope':scope,'q':'%_'})
        assert r.headers['X-Total-Count']=='1' and r.json()[0]['value']==str(entries[-1].id)


async def test_candidates_match_authority_and_do_not_use_another_accounts_subscriptions(world):
    db,client,_,reader,cookie,projects,spaces,teams,_,_=world
    client.cookies.set('radd_session',cookie)
    for scope,entry in [('project',projects[-1]),('space',spaces[-1])]:
        r=await client.get('/api/v1/notifications/subscription-options',params={'scope':scope})
        assert r.status_code==200 and r.headers['X-Total-Count']=='1'
        assert r.json()[0]['value']==str(entry.id)
    r=await client.get('/api/v1/notifications/subscription-options',params={'scope':'team'})
    assert r.json()==[] and r.headers['X-Total-Count']=='0'
    db.add(NotificationRule(user_id=reader.id,scope='space',scope_id=spaces[-1].id,channels={'page_created':'inbox'}));await db.flush()
    r=await client.get('/api/v1/notifications/subscription-options',params={'scope':'space'})
    assert r.json()==[]
    for scope in ['project','space','team']:
        r=await client.get('/api/v1/notifications/subscription-options',params={'scope':scope,'q':'no-such-directory-entry'})
        assert r.json()==[] and r.headers['X-Total-Count']=='0'


async def test_preferences_saved_names_are_bounded_and_later_add_remove_preserves_policy(world):
    db,client,admin,_,_,projects,spaces,teams,_,engine=world
    statements=[]
    def capture(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
    event.listen(engine.sync_engine,'before_cursor_execute',capture)
    try:
        r=await client.get('/api/v1/notifications/preferences')
        assert r.status_code==200,r.text
    finally:event.remove(engine.sync_engine,'before_cursor_execute',capture)
    names=[s for s in statements if 'page_spaces.name' in s]
    assert len(names)==1 and 'page_spaces.id IN' in names[0]
    assert 'page_spaces.description' not in names[0] and 'pages.space_id' not in names[0]
    original=r.json()['rules'];assert len(original)==150 and all(row['scope_label'] for row in original)
    rules=[{'scope':row['scope'],'scope_id':row['scope_id'],'channels':row['channels']} for row in original]
    rules += [{'scope':'own','channels':{'mentioned':'both'}}]
    for scope,entry in [('project',projects[-1]),('space',spaces[-1]),('team',teams[-1])]:
        rules.append({'scope':scope,'scope_id':str(entry.id),'channels':{'page_created' if scope=='space' else 'created':'inbox'}})
    saved=await client.put('/api/v1/notifications/preferences',json={'rules':rules,'email_digest':False})
    assert saved.status_code==200,saved.text
    assert len(saved.json()['rules'])==154 and saved.json()['email_digest'] is False
    for scope in ['project','space','team']:
        r=await client.get('/api/v1/notifications/subscription-options',params={'scope':scope,'q':'%_'})
        assert r.json()==[]
    rules=rules[:-3]
    r=await client.put('/api/v1/notifications/preferences',json={'rules':rules,'email_digest':False})
    assert r.status_code==200 and len(r.json()['rules'])==151
    for scope in ['project','space','team']:
        r=await client.get('/api/v1/notifications/subscription-options',params={'scope':scope,'q':'%_'})
        assert r.headers['X-Total-Count']=='1'


async def test_candidate_bounds_and_absent_wiki(world,monkeypatch):
    _,client,_,_,_,_,_,_,_,_=world
    for params in [{'scope':'own'},{'scope':'space','limit':201},{'scope':'team','offset':-1},{'scope':'project','q':'x'*201}]:
        assert (await client.get('/api/v1/notifications/subscription-options',params=params)).status_code==422
    import builtins
    original=builtins.__import__
    def absent(name,*args,**kwargs):
        if name=='radd.modules.pages':raise ImportError('wiki absent')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',absent)
    r=await client.get('/api/v1/notifications/subscription-options',params={'scope':'space'})
    assert r.status_code==200 and r.json()==[]
