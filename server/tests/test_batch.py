"""Several reads in one request (RADD-1561): the same answers, the same refusals."""

import pytest
import httpx

from radd.config import settings
from radd.db import get_session
from radd.modules.auth import service as auth
from radd.modules.auth.types import SESSION_COOKIE_NAME, InstanceRole, LoginMethod
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate

from _factories import make_user

API = "/api/v1"


@pytest.fixture
async def world(db, admin):
    from radd.app import create_app

    project = await projects.create_project(db, ProjectCreate(key="BAT", name="Batch"))
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="batched"), admin)
    outsider = await make_user(db, role=InstanceRole.MEMBER, name="Outsider")

    async def session_override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = session_override

    async def client(user):
        cookie = await auth.create_session(db, user, method=LoginMethod.PASSWORD)
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", cookies={SESSION_COOKIE_NAME: cookie}
        )

    return client, admin, outsider, project, item


async def test_each_answer_is_what_the_same_get_returns(world):
    client, admin, _outsider, project, item = world
    paths = [f"/items/{item.id}", f"/items/{item.id}/history", f"/states?project_id={project.id}", "/items/00000000-0000-0000-0000-000000000000"]
    async with await client(admin) as http:
        singles = [await http.get(API + path) for path in paths]
        batched = await http.post(API + "/batch", json={"requests": paths})
    assert batched.status_code == 200
    answers = batched.json()
    assert [a["status"] for a in answers] == [r.status_code for r in singles] == [200, 200, 200, 404]
    for answer, single in zip(answers, singles, strict=True):
        assert answer["body"] == single.json()


async def test_a_batch_carries_the_callers_authority_and_no_more(world):
    client, _admin, outsider, _project, item = world
    async with await client(outsider) as http:
        alone = await http.get(API + f"/items/{item.id}")
        batched = (await http.post(API + "/batch", json={"requests": [f"/items/{item.id}"]})).json()
    # Whatever the plain GET refuses, the batch refuses the same way.
    assert alone.status_code in (403, 404) and batched[0]["status"] == alone.status_code
    assert batched[0]["body"] == alone.json()
    # And with no session at all, each sub-request is anonymous too.
    from radd.app import create_app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as anonymous:
        refused = await anonymous.post(API + "/batch", json={"requests": ["/users"]})
    assert refused.status_code == 200 and refused.json()[0]["status"] in (401, 403)


@pytest.mark.parametrize(
    "requests",
    [
        [],
        "not a list",
        ["items"],  # not a path
        ["//evil.example/x"],
        ["https://evil.example/x"],
        ["/items/../../health"],
        ["/batch"],
        ["/batch/"],
        ["/x"] * 31,
    ],
)
async def test_what_a_batch_refuses(world, requests):
    client, admin, *_ = world
    async with await client(admin) as http:
        response = await http.post(API + "/batch", json={"requests": requests})
    assert response.status_code == 422, response.text


async def test_only_json_answers_are_carried(world, monkeypatch):
    client, admin, *_ = world
    monkeypatch.setattr(settings, "metrics_enabled", True)
    async with await client(admin) as http:
        # A path outside the API prefix cannot be named: every path is taken under it.
        answer = (await http.post(API + "/batch", json={"requests": ["/../metrics"]}))
    assert answer.status_code == 422
