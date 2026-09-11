"""Provisioning references are bounded; recoverable SQL failure cannot poison sign-in."""
import uuid
import httpx
import pytest
from sqlalchemy import event, select, delete
from radd.app import create_app
from radd.db import get_session
from radd.modules.auth import service as auth, grants as auth_grants
from radd.modules.auth.models import User, Role, GlobalRoleGrant
from radd.modules.auth.schemas import TokenCreate
from radd.modules.projects.models import Project
from radd.modules.teams.models import Team, TeamMember
from radd.modules.groups.service import Group
from radd.modules.sso import registry, service
from radd.modules.sso.schemas import SsoProviderUpdate
from test_sso_providers import db, _provider  # noqa: F401


@pytest.fixture
async def world(db):
    prefix=uuid.uuid4().hex[:5]
    admin=User(name='Admin',email=prefix+'admin@test.invalid',instance_role='admin')
    roles=[Role(name=f'{prefix} role {i:03}',key=prefix+str(i),permissions=['item.read']) for i in range(126)]
    projects=[Project(name=f'{prefix} project {i:03}',key='P'+prefix.upper()+str(i)) for i in range(126)]
    teams=[Team(name=f'{prefix} team {i:03}') for i in range(126)]
    db.add_all([admin,*roles,*projects,*teams]);await db.flush()
    provider=await _provider(db,provisioning_rules=[{'name':f'Rule {i:03}','grants':[{'role_id':roles[i].id,'project_id':projects[i].id}],'team_ids':[teams[i].id]} for i in range(126)])
    app=create_app()
    async def override():yield db
    app.dependency_overrides[get_session]=override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',cookies={'radd_session':await auth.create_session(db,admin)}) as client:
        yield db,client,admin,provider,roles,projects,teams,prefix


async def test_rule_children_batch_and_reference_projection(world):
    db,client,_,provider,roles,projects,teams,_=world
    statements=[]
    def capture(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
    engine=db.bind.sync_engine
    event.listen(engine,'before_cursor_execute',capture)
    try:
        found=await registry.provisioning_rules(db,provider.id)
        assert len(found)==126 and len(statements)==3
        assert all(len(grants)==1 and len(ids)==1 for _,grants,ids in found)
        statements.clear()
        r=await client.post('/api/v1/sso/provisioning-references',json={'role_ids':[str(r.id) for r in roles[100:]],'project_ids':[str(p.id) for p in projects[100:]],'team_ids':[str(t.id) for t in teams[100:]]})
        assert r.status_code==200,r.text
        assert r.json()=={'roles':{str(r.id):r.name for r in roles[100:]},'projects':{str(p.id):p.key for p in projects[100:]},'teams':{str(t.id):t.name for t in teams[100:]}}
        hydration=[s for s in statements if any(x in s for x in ['roles.name','projects.key','teams.name'])]
        assert len(hydration)==3 and all(' IN ' in s for s in hydration)
        assert all('roles.permissions' not in s and 'team_managers' not in s for s in hydration)
    finally:event.remove(engine,'before_cursor_execute',capture)


async def test_reference_gates_limits_missing_and_assignable_roles(world):
    db,client,_,_,roles,projects,teams,prefix=world
    assert (await client.post('/api/v1/sso/provisioning-references',json={'role_ids':[str(roles[0].id)]*101})).status_code==422
    r=await client.post('/api/v1/sso/provisioning-references',json={'team_ids':[str(uuid.uuid4())]});assert r.json()=={'roles':{},'projects':{},'teams':{}}
    seen=[]
    for offset in [0,50,100]:
        r=await client.get('/api/v1/roles/assignable/options',params={'q':prefix,'offset':offset,'limit':50});assert r.status_code==200 and r.headers['X-Total-Count']=='126';seen.extend(row['value'] for row in r.json())
    assert seen==[str(r.id) for r in roles]
    assert (await client.get('/api/v1/roles/assignable/options',params={'q':'baseline'})).json()==[]
    actor=User(name='Restricted admin',email=prefix+'key@test.invalid',instance_role='admin');db.add(actor);await db.flush()
    _,token=await auth.create_api_token(db,actor,TokenCreate(name='catalog only',scopes={'global':['role.read']}))
    client.cookies.clear();client.headers['Authorization']='Bearer '+token
    assert (await client.post('/api/v1/sso/provisioning-references',json={})).status_code==403
    assert (await client.get('/api/v1/roles/assignable/options',params={'value':str(roles[-1].id)})).json()[0]['value']==str(roles[-1].id)


async def test_sql_refusal_preserves_account_other_rules_and_team_membership(world,monkeypatch):
    db,_,admin,provider,roles,projects,teams,prefix=world
    group=Group(name=prefix+' group',dn='CN='+prefix);db.add(group);await db.flush()
    db.add(TeamMember(team_id=teams[-1].id,group_id=group.id));await db.flush()
    await registry.update_provider(db,provider.id,SsoProviderUpdate(provisioning_rules=[
        {'name':'Catch all','grants':[{'role_id':roles[0].id}]},
        {'name':'Staff','domains':['radd-hq.com'],'grants':[{'role_id':roles[-1].id,'project_id':projects[-1].id}],'team_ids':[teams[-1].id]},
        {'name':'Other','domains':['other.invalid'],'grants':[{'role_id':roles[1].id}]}]))
    real=auth_grants.create_grant
    async def refuse(session,role_id,**kwargs):
        if role_id==roles[0].id:
            session.add(User(name='Duplicate SQL failure',email=admin.email));await session.flush()
        return await real(session,role_id,**kwargs)
    monkeypatch.setattr(auth_grants,'create_grant',refuse)
    claims={'sub':prefix+'subject','email':prefix+'new@radd-hq.com','email_verified':True,'name':'New account'}
    user=await service.provision(db,provider,claims)
    await db.flush() # proves the SQL error did not leave the outer transaction failed
    held=list(await db.scalars(select(GlobalRoleGrant).where(GlobalRoleGrant.user_id==user.id)))
    assert [(g.role_id,g.project_id) for g in held]==[(roles[-1].id,projects[-1].id)]
    member=await db.scalar(select(TeamMember).where(TeamMember.team_id==teams[-1].id,TeamMember.user_id==user.id));assert member
    assert await db.scalar(select(TeamMember).where(TeamMember.team_id==teams[-1].id,TeamMember.group_id==group.id))
    await db.execute(delete(GlobalRoleGrant).where(GlobalRoleGrant.user_id==user.id));await db.delete(member);await db.flush()
    assert (await service.provision(db,provider,claims)).id==user.id
    assert not list(await db.scalars(select(GlobalRoleGrant).where(GlobalRoleGrant.user_id==user.id)))
    assert not await db.scalar(select(TeamMember).where(TeamMember.team_id==teams[-1].id,TeamMember.user_id==user.id))


async def test_team_sql_refusal_does_not_discard_other_memberships(world,monkeypatch):
    from radd.modules.teams import service as teams_service
    db,_,admin,provider,_,_,teams,prefix=world
    await registry.update_provider(db,provider.id,SsoProviderUpdate(provisioning_rules=[{'team_ids':[teams[0].id,teams[-1].id]}]))
    real=teams_service.add_team_member
    async def refuse(session,team_id,user_id,**kwargs):
        if team_id==teams[0].id:
            session.add(User(name='Duplicate SQL failure',email=admin.email));await session.flush()
        return await real(session,team_id,user_id,**kwargs)
    monkeypatch.setattr(teams_service,'add_team_member',refuse)
    user=await service.provision(db,provider,{'sub':prefix+'team','email':prefix+'team@radd-hq.com','email_verified':True})
    await db.flush()
    ids=list(await db.scalars(select(TeamMember.team_id).where(TeamMember.user_id==user.id)))
    assert ids==[teams[-1].id]
