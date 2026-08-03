"""A requester who can ONLY file through a form (spec 73 + RADD-785).

This is the narrowest real actor on the instance: no project grants, no
`item.create`, an empty Baseline — someone whose entire relationship with Radd
is "submit a request and watch it". The portal has to work for exactly them, and
the rest of the app has to be quiet rather than hostile.

Written when RADD-788 landed, to pin that the floor-gate rework did not touch
this path and that the surfaces a requester's shell loads answer empty rather
than refusing.
"""

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import Role, User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture(scope="module")
async def world():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        from radd.modules.auth import service as auth_service
        from radd.modules.forms import service as forms_service
        from radd.modules.forms.models import FormShare
        from radd.modules.forms.schemas import FormCreate

        baseline = (
            await session.execute(
                select(Role).where(Role.key == BuiltinRoleKey.BASELINE.value)
            )
        ).scalar_one()
        previous = list(baseline.permissions or [])
        baseline.permissions = []

        admin = User(
            email=f"padm-{uuid.uuid4().hex[:8]}@example.com",
            name="Admin",
            instance_role=InstanceRole.ADMIN.value,
        )
        # The requester: an ordinary member holding NOTHING, anywhere.
        requester = User(
            email=f"req-{uuid.uuid4().hex[:8]}@example.com",
            name="Requester",
            instance_role=InstanceRole.MEMBER.value,
        )
        session.add_all([admin, requester])
        await session.flush()

        project = await projects_service.create_project(
            session, ProjectCreate(key=f"PT{uuid.uuid4().hex[:4].upper()}", name="Portal")
        )
        form = await forms_service.create_form(
            session,
            FormCreate(project_id=project.id, name="Request something", enabled=True),
            actor=admin,
        )
        # The share IS the grant (spec 73) — no permission atom involved.
        session.add(FormShare(form_id=form.id, user_id=requester.id))
        await session.flush()

        _, token = await auth_service.create_api_token(
            session, requester, TokenCreate(name="portal")
        )
        await session.commit()
        yield {"token": token, "form_id": str(form.id), "project_id": str(project.id)}

        baseline = (
            await session.execute(
                select(Role).where(Role.key == BuiltinRoleKey.BASELINE.value)
            )
        ).scalar_one()
        baseline.permissions = previous
        await session.commit()
    await engine.dispose()


@pytest.fixture(scope="module")
def app():
    from radd.app import create_app

    return create_app()


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_the_portal_works_without_item_create(client, world):
    """The whole point of spec 73: the SHARE is the grant. A requester holding no
    permission atom anywhere sees the form, submits it, and gets an item."""
    h = _auth(world["token"])

    listing = await client.get("/api/v1/portal/forms", headers=h)
    assert listing.status_code == 200
    assert any(
        card["id"] == world["form_id"]
        for group in listing.json()
        for card in group["forms"]
    ), "the shared form should appear in the requester's portal"

    render = await client.get(f"/api/v1/portal/forms/{world['form_id']}", headers=h)
    assert render.status_code == 200

    submitted = await client.post(
        f"/api/v1/portal/forms/{world['form_id']}/submit",
        headers=h,
        json={"title": "The render farm is on fire", "values": {}},
    )
    assert submitted.status_code == 201, submitted.text


async def test_a_requester_sees_the_request_they_filed(client, world):
    """RADD-785. Filing into a project they cannot read must not mean the request
    vanishes the moment it is created."""
    h = _auth(world["token"])
    await client.post(
        f"/api/v1/portal/forms/{world['form_id']}/submit",
        headers=h,
        json={"title": "Second request", "values": {}},
    )
    mine = await client.get("/api/v1/portal/requests", headers=h)
    assert mine.status_code == 200
    assert mine.json(), "the requester's own requests should be listed back to them"


async def test_the_member_form_path_still_needs_item_create(client, world):
    """The portal is the requester door; the member-facing `/forms/{id}` route is
    a different one and still asks for `item.create` on the project. Keeping them
    apart is what lets the portal be open without widening anything."""
    h = _auth(world["token"])
    assert (await client.get(f"/api/v1/forms/{world['form_id']}", headers=h)).status_code == 403


async def test_the_rest_of_the_app_is_quiet_rather_than_hostile(client, world):
    """RADD-788's rule, seen from the narrowest actor: the surfaces a requester's
    shell loads answer EMPTY. Before it, each one was a 403 toast on arrival."""
    h = _auth(world["token"])
    for path in ("/api/v1/projects", "/api/v1/views", "/api/v1/dashboards", "/api/v1/labels"):
        response = await client.get(path, headers=h)
        assert response.status_code == 200, f"{path} -> {response.status_code}"
        assert response.json() == [], f"{path} leaked rows to a requester"
