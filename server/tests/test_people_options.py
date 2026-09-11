"""Email/team vocabulary remains bounded and credential-scoped at the HTTP seam."""
import uuid
import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.teams.models import Team


@pytest.mark.parametrize('resource,permission', [('users','user.manage'),('teams','team.read')])
async def test_people_option_window_privacy_and_credentials(resource,permission):
    engine=create_async_engine(settings.database_url)
    async with async_sessionmaker(engine,expire_on_commit=False)() as db:
        prefix='people-'+uuid.uuid4().hex[:8]
        owner=User(email=prefix+'-admin@test.invalid',name='Owner',instance_role='admin')
        member=User(email=prefix+'-member@test.invalid',name='Member',instance_role='member')
        db.add_all([owner,member]);await db.flush()
        _,token=await auth.create_api_token(db,owner,TokenCreate(name='Vocabulary',scopes={'global':[permission]}))
        _,empty=await auth.create_api_token(db,owner,TokenCreate(name='No vocabulary',scopes={}))
        cookie=await auth.create_session(db,member)
        rows=[]
        for i in range(126):
            name=f'{prefix} choice {i:03}'
            row=User(email=f'{prefix}-{i:03}@test.invalid',name=name,source='service' if i==124 else 'email' if i==125 else 'local') if resource=='users' else Team(name=name)
            db.add(row);rows.append(row)
        extra=User(email=prefix+'-%_@test.invalid',name=prefix+' literal %_') if resource=='users' else Team(name=prefix+' literal %_')
        db.add(extra)
        if resource=='users':db.add(User(email=prefix+'-inactive@test.invalid',name=prefix+' inactive',active=False))
        await db.flush()
        async def override():yield db
        app=create_app();app.dependency_overrides[get_session]=override
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Authorization':f'Bearer {token}'}) as client:
            url=f'/api/v1/{resource}/options';seen=[];sql=[]
            def record(conn,cursor,statement,parameters,context,executemany):sql.append(statement)
            event.listen(engine.sync_engine,'before_cursor_execute',record)
            try:
                for offset,count in [(0,50),(50,50),(100,26)]:
                    response=await client.get(url,params={'q':prefix+' choice','offset':offset,'limit':50})
                    assert response.status_code==200,response.text
                    assert response.headers['X-Total-Count']=='126' and len(response.json())==count
                    assert all(set(row)=={'value','label','hint'} for row in response.json())
                    seen.extend(row['value'] for row in response.json())
            finally:event.remove(engine.sync_engine,'before_cursor_execute',record)
            assert set(seen)=={row.email if resource=='users' else row.name for row in rows} and len(seen)==len(set(seen))
            if resource=='users':
                vocabulary=[query for query in sql if 'users.email AS value' in query]
                assert vocabulary and all('password_hash' not in query and 'last_login' not in query for query in vocabulary)
            else:assert not any('team_managers' in query for query in sql)
            response=await client.get(url,params={'q':'%_','limit':50})
            assert response.headers['X-Total-Count']=='1' and response.json()[0]['label']==extra.name
            selected=rows[125].email if resource=='users' else rows[125].name
            response=await client.get(url,params={'value':selected,'limit':1})
            assert response.headers['X-Total-Count']=='1' and response.json()[0]['value']==selected
            response=await client.get(url,params={'q':f'  {prefix.upper()} CHOICE 125  '})
            assert len(response.json())==1
            for params in ({'limit':0},{'limit':201},{'offset':-1},{'q':'x'*201}):assert (await client.get(url,params=params)).status_code==422
            if resource=='users':
                response=await client.get(url,params={'q':prefix+' inactive'})
                assert response.json()==[] and response.headers['X-Total-Count']=='0'
            db.info.clear()
            response=await client.get(url,headers={'Authorization':f'Bearer {empty}'},params={'q':prefix})
            if resource=='users':assert response.status_code==403
            else:assert response.status_code==200 and response.json()==[] and response.headers['X-Total-Count']=='0'
            db.info.clear();client.headers.pop('Authorization')
            response=await client.get(url,cookies={'radd_session':cookie},params={'q':prefix})
            if resource=='users':assert response.status_code==403
            response=await client.get('/api/v1/users/directory',cookies={'radd_session':cookie},params={'q':prefix,'limit':50})
            assert response.status_code==200 and all('email' not in row for row in response.json())
        await db.rollback()
    await engine.dispose()
