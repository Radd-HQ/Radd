"""Uploader ownership cannot escape a credential or a lost parent audience."""
import httpx
from sqlalchemy import delete
from radd.app import create_app
from radd.db import get_session
from radd.modules.access import service as access
from radd.modules.attachments import acl
from radd.modules.auth import service as auth
from radd.modules.auth.models import GlobalRoleGrant
from radd.modules.auth.schemas import TokenCreate
from test_attachment_acl import db, setup  # noqa: F401
from radd.modules.auth.types import LoginMethod


async def test_uploader_grants_require_parent_and_writable_credential(db,setup):
    admin,member,item,attachment=setup
    app=create_app()
    async def override():yield db
    app.dependency_overrides[get_session]=override
    params={'resource_type':'attachment','resource_id':str(attachment.id)}
    body={**params,'subject_type':'user','subject_id':str(member.id),'access':'read'}
    cookie=await auth.create_session(db,admin, method=LoginMethod.PASSWORD)
    keys=[]
    for scopes in [{},{'projects':{str(item.project_id):['item.read']}},{'projects':{str(item.project_id):['item.read','attachment.create']}}]:
        _,key=await auth.create_api_token(db,admin,TokenCreate(name='scoped',scopes=scopes));keys.append(key)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        for key in keys[:2]:
            client.headers['Authorization']='Bearer '+key
            for path in ['/api/v1/grants','/api/v1/grants/directory']:
                assert (await client.get(path,params=params)).status_code==403
            assert (await client.post('/api/v1/grants',json=body)).status_code==403
            assert await access.list_for_resource(db,'attachment',str(attachment.id))==[]
        client.headers['Authorization']='Bearer '+keys[2]
        response=await client.post('/api/v1/grants',json=body);assert response.status_code==201,response.text
        grant_id=response.json()[0]['id']
        assert (await client.delete('/api/v1/grants/'+grant_id)).status_code==204
        client.headers.pop('Authorization')
        client.cookies.set('radd_session',cookie)
        assert (await client.post('/api/v1/grants',json=body)).status_code==201
        # A former uploader without access to the parent cannot inspect or edit
        # its grants, even with a normal browser credential.
        attachment.created_by=member.id
        await db.execute(delete(GlobalRoleGrant).where(GlobalRoleGrant.user_id==member.id))
        await db.flush();db.info.clear()
        client.cookies.set('radd_session',await auth.create_session(db,member, method=LoginMethod.PASSWORD))
        assert not await acl.attachment_readable(db,member,attachment)
        assert (await client.get('/api/v1/grants/directory',params=params)).status_code==403
        assert (await client.delete('/api/v1/grants/'+(await access.list_for_resource(db,'attachment',str(attachment.id)))[0].id.hex)).status_code==403
