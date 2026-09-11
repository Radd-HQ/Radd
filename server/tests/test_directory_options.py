"""Owner-supplied choices filter authority and duplicates before SQL windows."""
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
from radd.modules.projects.models import Project
from radd.modules.workflow.models import State
from radd.modules.releases.models import Release
from radd.modules.itemtypes.models import IssueType
from radd.modules.forms.models import Form


@pytest.mark.parametrize('resource,model,name_field,reference', [
    ('states', State, 'name', False), ('releases', Release, 'version', False),
    ('issue-types', IssueType, 'name', True), ('forms', Form, 'name', True),
])
async def test_option_visibility_deduplication_search_and_lookup(resource, model, name_field, reference):
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        actor = User(email=f'options-{uuid.uuid4()}@test.invalid', name='Owner', instance_role='admin')
        prefix = 'O'+uuid.uuid4().hex[:7]
        projects = [Project(key=prefix+str(i),name=f'Options project {i}') for i in range(3)]
        db.add_all([actor,*projects]); await db.flush()
        scopes = {'projects': {str(projects[0].id): ['item.read','form.manage'],str(projects[1].id): ['item.read']}}
        _,token = await auth.create_api_token(db,actor,TokenCreate(name='Choices reader',scopes=scopes))
        _,empty_token = await auth.create_api_token(db,actor,TokenCreate(name='No choices',scopes={}))
        rows=[]
        for index,project in enumerate(projects):
            for i in range(126):
                label=f'{prefix} value {i:03}' if index<2 else f'{prefix} HIDDEN {i:03}'
                data={'project_id':project.id,name_field:label}
                if model is Release:data['name']='Release'
                if model is State:data.update(category='backlog',position=i)
                if model is IssueType:data['color']='#64748b'
                row=model(**data);db.add(row);rows.append((row,index))
        extra=({'name':'Release'} if model is Release else {}) | ({'category':'backlog','position':999} if model is State else {}) | ({'color':'#64748b'} if model is IssueType else {})
        literal=model(project_id=projects[0].id,**{name_field:prefix+' %_',**extra})
        db.add(literal);await db.flush()
        async def override():yield db
        app=create_app();app.dependency_overrides[get_session]=override
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Authorization':f'Bearer {token}'}) as client:
            url=f'/api/v1/{resource}/options'
            permitted=[row for row,index in rows if index==0 or (index==1 and resource!='forms')]
            expected={str(row.id) if reference else getattr(row,name_field) for row in [*permitted,literal]}
            seen=[];statements=[]
            def record(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
            event.listen(engine.sync_engine,'before_cursor_execute',record)
            try:
                for offset in range(0,len(expected),50):
                    response=await client.get(url,params={'q':prefix,'limit':50,'offset':offset})
                    assert response.status_code==200,response.text
                    assert int(response.headers['X-Total-Count'])==len(expected)
                    assert len(response.json())<=50
                    assert all(set(row)=={'value','label','hint'} for row in response.json())
                    seen.extend(row['value'] for row in response.json())
            finally:event.remove(engine.sync_engine,'before_cursor_execute',record)
            assert len(seen)==len(set(seen)) and set(seen)==expected
            assert not any('projects.next_number' in sql for sql in statements)
            response=await client.get(url,params={'q':'%_','limit':1})
            assert response.headers['X-Total-Count']=='1' and response.json()[0]['label']==prefix+' %_'
            response=await client.get(url,params={'q':f'  {prefix.lower()} value 125  ','limit':50})
            assert len(response.json())==(2 if reference and resource!='forms' else 1)
            selected=rows[125][0];value=str(selected.id) if reference else getattr(selected,name_field)
            response=await client.get(url,params={'value':value,'limit':1})
            assert response.json()[0]['value']==value and response.headers['X-Total-Count']=='1'
            response=await client.get(url,params={'q':prefix,'project_id':str(projects[0].id),'limit':200})
            assert len(response.json())==127 and response.headers['X-Total-Count']=='127'
            if reference:assert all(row['hint']==projects[0].key for row in response.json())
            hidden=rows[-1][0]
            response=await client.get(url,params={'value':str(hidden.id) if reference else getattr(hidden,name_field),'limit':1})
            assert response.json()==[] and response.headers['X-Total-Count']=='0'
            for params in ({'limit':201},{'limit':0},{'offset':-1},{'q':'x'*201}):
                assert (await client.get(url,params=params)).status_code==422
            db.info.clear()  # real requests get separate sessions/authority memos
            response=await client.get(url,params={'q':prefix},headers={'Authorization':f'Bearer {empty_token}'})
            assert response.status_code==200 and response.json()==[] and response.headers['X-Total-Count']=='0'
        await db.rollback()
    await engine.dispose()
