"""Generic management paging keeps policy complete and names permission-safe."""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import event

from radd.clock import utcnow
from radd.modules.access import service as grants
from radd.modules.access.models import AccessGrant
from radd.modules.auth import service as auth
from radd.modules.auth.models import GlobalRoleGrant, Role, User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.fields import service as fields
from radd.modules.fields.schemas import FieldDefinitionCreate
from radd.modules.projects.models import Project
from test_space_access_directory import access_world  # noqa: F401
from radd.modules.auth.types import LoginMethod


@pytest.fixture
async def world(access_world):
    db,client,_,_,_,roles,people,teams,groups,cookie,engine,prefix=access_world
    field=await fields.create_field(db,FieldDefinitionCreate(key='f'+prefix,name=prefix+' field',type='text'))
    project=Project(key='H'+prefix.upper(),name=prefix+' hidden project');db.add(project);await db.flush()
    start=utcnow()-timedelta(days=1)
    catalogs=[('user',people),('role',roles),('team',teams),('group',groups)]
    rows=[AccessGrant(resource_type='field',resource_id=str(field.id),subject_type=catalogs[i%4][0],
        subject_id=catalogs[i%4][1][i].id,access='read',effect='deny' if i==121 else 'allow',
        project_id=project.id if i==125 else None,created_at=start,
        expires_at=start if i==124 else None) for i in range(126)]
    db.add_all(rows);await db.flush()
    yield db,client,field,project,rows,roles,people,teams,groups,cookie,engine,prefix


async def test_windows_privacy_expiry_and_narrow_hydration(world):
    db,client,field,project,grants_,roles,people,teams,groups,_,engine,_=world
    params={'resource_type':'field','resource_id':str(field.id),'limit':50}
    captured=[]
    def capture(conn,cursor,sql,parameters,context,executemany):captured.append(sql)
    event.listen(engine.sync_engine,'before_cursor_execute',capture)
    try:
        seen=[]
        for offset,size in [(0,50),(50,50),(100,26)]:
            response=await client.get('/api/v1/grants/directory',params={**params,'offset':offset})
            assert response.status_code==200,response.text
            assert response.headers['X-Total-Count']=='126'
            assert len(response.json())==size;seen.extend(response.json())
        assert [r['id'] for r in seen]==[str(g.id) for g in sorted(grants_,key=lambda g:g.id)]
        names={str(r.id):r.name for r in [*roles,*people,*teams,*groups]}
        for row in seen:
            assert row['subject_name']==names[row['subject_id']]
            assert 'permissions' not in row and 'email' not in row and 'manager_ids' not in row
        assert next(r for r in seen if r['id']==str(grants_[124].id))['expired']
        assert next(r for r in seen if r['id']==str(grants_[125].id))['project_key']==project.key
        assert len(await grants.list_for_resource(db,'field',str(field.id)))==125
        lean=[s for s in captured if 'anon_1.name' in s and ' IN (' in s and 'FROM (SELECT' in s]
        assert lean and all('permissions' not in sql and 'password_hash' not in sql for sql in lean)
        response=await client.get('/api/v1/grants/directory',params={**params,'q':'%_'})
        assert len(response.json())==1 and response.json()[0]['subject_id']==str(people[0].id)
    finally:event.remove(engine.sync_engine,'before_cursor_execute',capture)


async def test_resource_guard_name_search_and_credential_limits(world):
    db,client,field,project,rows,roles,people,teams,groups,cookie,_,prefix=world
    client.cookies.set('radd_session',cookie)
    params={'resource_type':'field','resource_id':str(field.id)}
    for path in ['/api/v1/grants','/api/v1/grants/directory']:
        assert (await client.get(path,params=params)).status_code==403
    delegate=User(name='Field manager',email=prefix+'field@test.invalid')
    manager=Role(key=prefix+'field',name='Field manager',permissions=['field.manage'])
    db.add_all([delegate,manager]);await db.flush()
    db.add(GlobalRoleGrant(user_id=delegate.id,role_id=manager.id));await db.flush();db.info.clear()
    client.cookies.set('radd_session',await auth.create_session(db,delegate, method=LoginMethod.PASSWORD))
    definitions=await client.get('/api/v1/fields',params={'q':field.name,'limit':50})
    assert definitions.status_code==200 and [r['id'] for r in definitions.json()]==[str(field.id)]
    response=await client.get('/api/v1/grants/directory',params={**params,'limit':200});assert response.status_code==200,response.text
    assert len(response.json())==126
    for row in response.json():
        if row['subject_type']!='user':assert row['subject_name'] is None
        if row['project_id']:assert row['project_key'] is None
    for secret in [roles[1].name,teams[2].name,groups[3].name,project.key]:
        response=await client.get('/api/v1/grants/directory',params={**params,'q':secret})
        assert response.status_code==200 and response.json()==[] and response.headers['X-Total-Count']=='0'
    _,key=await auth.create_api_token(db,delegate,TokenCreate(name='empty',scopes={}))
    client.cookies.clear();client.headers['Authorization']='Bearer '+key;db.info.clear()
    assert (await client.get('/api/v1/grants/directory',params=params)).status_code==403
    assert (await client.delete('/api/v1/grants/'+str(rows[0].id))).status_code==403
    hidden=await client.get('/api/v1/fields',params={'limit':50})
    assert hidden.status_code==200 and hidden.json()==[] and hidden.headers['X-Total-Count']=='0'


async def test_expired_grant_is_reachable_for_replacement_and_limits(world):
    db,client,field,_,rows,_,people,_,_,_,_,_=world
    params={'resource_type':'field','resource_id':str(field.id)}
    for query in [{'limit':201},{'limit':0},{'offset':-1},{'q':'a'*201}]:
        assert (await client.get('/api/v1/grants/directory',params={**params,**query})).status_code==422
    expired=rows[124]
    assert (await client.delete('/api/v1/grants/'+str(expired.id))).status_code==204
    response=await client.post('/api/v1/grants',json={**params,'subject_type':'user','subject_id':str(people[124].id),'access':'read','effect':'deny'})
    assert response.status_code==201,response.text
    current=await grants.list_for_resource(db,'field',str(field.id))
    assert len(current)==126 and {g.id for g in rows[:-2]}<={g.id for g in current}
