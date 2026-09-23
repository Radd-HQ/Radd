"""Project grants use actual scope visibility and preserve delegated write boundaries."""
import uuid
import pytest
from sqlalchemy import select
from radd.modules.auth import service as auth
from radd.modules.auth.models import GlobalRoleGrant, Role, User
from radd.modules.projects.models import Project
from test_space_access_directory import access_world  # noqa: F401
from radd.modules.auth.types import LoginMethod


@pytest.fixture
async def project_world(access_world):
    db,client,_,_,grants,roles,people,teams,groups,cookie,engine,prefix=access_world
    project=await db.scalar(select(Project).where(Project.key=='P'+prefix.upper()))
    hidden=Project(key='H'+prefix.upper(),name=prefix+'hidden');db.add(hidden);await db.flush()
    for row in grants:row.space_id=None;row.project_id=project.id
    reader_role=await db.get(Role,grants[-1].role_id);reader_role.permissions=['item.read']
    db.add(GlobalRoleGrant(role_id=roles[0].id,project_id=hidden.id,user_id=people[0].id))
    await db.flush();db.info.clear()
    yield db,client,project,hidden,grants,roles,people,teams,groups,cookie,prefix


async def test_project_grant_windows_names_and_legacy_visibility(project_world):
    db,client,project,hidden,grants,roles,people,teams,groups,cookie,prefix=project_world
    seen=[]
    for offset,count in [(0,50),(50,50),(100,26)]:
        r=await client.get(f'/api/v1/role-grants/by-project/{project.id}',params={'limit':50,'offset':offset})
        assert r.status_code==200 and r.headers['X-Total-Count']=='126'
        assert len(r.json())==count;seen.extend(r.json())
    assert [row['id'] for row in seen]==[str(row.id) for row in sorted(grants,key=lambda row:row.id)]
    assert all(row['project_id']==str(project.id) and row['space_id'] is None for row in seen)
    assert all(row['role_name'] for row in seen)
    assert any(row['expired'] for row in seen) and any(row['subject_active'] is False for row in seen)
    client.cookies.set('radd_session',cookie)
    for path in [f'/api/v1/role-grants/by-project/{hidden.id}',f'/api/v1/role-grants?project_id={hidden.id}']:
        assert (await client.get(path)).status_code==404
    assert (await client.get(f'/api/v1/role-grants?project_id={project.id}')).status_code==200
    r=await client.get(f'/api/v1/role-grants/by-project/{project.id}')
    assert r.status_code==200 and all(row['role_name'] is None for row in r.json())
    for secret in [roles[0].name,teams[1].name]:
        r=await client.get(f'/api/v1/role-grants/by-project/{project.id}',params={'q':secret})
        assert r.json()==[] and r.headers['X-Total-Count']=='0'
    r=await client.get(f'/api/v1/role-grants/by-project/{project.id}',params={'q':groups[2].name})
    assert r.status_code==200 and r.headers['X-Total-Count']=='1' # member-floor group names remain readable


async def test_project_delegate_and_revoke_only_preserve_scope_and_coverage(project_world):
    db,client,project,hidden,grants,roles,people,teams,groups,_,prefix=project_world
    delegate=User(name='Delegate',email=prefix+'delegate@test.invalid')
    revoker=User(name='Revoker',email=prefix+'revoker@test.invalid')
    can_grant=Role(key=prefix+'delegate',name='Delegate',permissions=['item.read','member.create','member.delete'])
    can_revoke=Role(key=prefix+'revoke',name='Revoke',permissions=['item.read','member.delete'])
    too_broad=Role(key=prefix+'wide',name='Wide',permissions=['global.manage'])
    db.add_all([delegate,revoker,can_grant,can_revoke,too_broad]);await db.flush()
    db.add_all([GlobalRoleGrant(user_id=delegate.id,role_id=can_grant.id,project_id=project.id),GlobalRoleGrant(user_id=revoker.id,role_id=can_revoke.id,project_id=project.id)])
    await db.flush();db.info.clear()
    client.cookies.set('radd_session',await auth.create_session(db,delegate, method=LoginMethod.PASSWORD))
    original={row.id for row in grants};created=[]
    for subject in [{'user_id':str(people[-1].id)},{'team_id':str(teams[-1].id)},{'group_id':str(groups[-1].id)}]:
        r=await client.post('/api/v1/role-grants',json={'role_id':str(roles[-1].id),'project_ids':[str(project.id)],**subject})
        assert r.status_code==201,r.text;created.append(r.json()[0]['id'])
    for body in [{'role_id':str(too_broad.id),'project_ids':[str(project.id)]},{'role_id':str(roles[-1].id),'project_ids':[str(hidden.id)]},{'role_id':str(roles[-1].id),'project_ids':[]}]:
        r=await client.post('/api/v1/role-grants',json={**body,'user_id':str(people[-1].id)})
        assert r.status_code==403,r.text
    client.cookies.set('radd_session',await auth.create_session(db,revoker, method=LoginMethod.PASSWORD));db.info.clear()
    r=await client.post('/api/v1/role-grants',json={'role_id':str(roles[0].id),'project_ids':[str(project.id)],'user_id':str(people[-1].id)})
    assert r.status_code==403
    for id in created:assert (await client.delete('/api/v1/role-grants/'+id)).status_code==204
    actual=set(await db.scalars(select(GlobalRoleGrant.id).where(GlobalRoleGrant.project_id==project.id)))
    assert original<=actual


async def test_project_directory_bounds_and_missing_are_non_oracular(project_world):
    _,client,project,_,_,_,_,_,_,cookie,_=project_world
    for params in [{'limit':201},{'offset':-1},{'q':'x'*201}]:
        assert (await client.get(f'/api/v1/role-grants/by-project/{project.id}',params=params)).status_code==422
    client.cookies.set('radd_session',cookie)
    assert (await client.get(f'/api/v1/role-grants/by-project/{uuid.uuid4()}')).status_code==404


async def test_project_directory_intersects_admin_credentials(project_world):
    from radd.modules.auth.schemas import TokenCreate
    db,client,project,hidden,grants,_,_,_,_,_,prefix=project_world
    actor=User(name='Scoped key',email=prefix+'key@test.invalid',instance_role='admin');db.add(actor);await db.flush()
    _,key=await auth.create_api_token(db,actor,TokenCreate(name='project read',scopes={'projects':{str(project.id):['item.read']}}))
    client.cookies.clear();client.headers['Authorization']='Bearer '+key
    r=await client.get(f'/api/v1/role-grants/by-project/{project.id}')
    assert r.status_code==200 and all(row['role_name'] is None for row in r.json())
    for path in [f'/api/v1/role-grants/by-project/{hidden.id}',f'/api/v1/role-grants?project_id={hidden.id}']:
        assert (await client.get(path)).status_code==404
    assert (await client.delete('/api/v1/role-grants/'+str(grants[0].id))).status_code==403
