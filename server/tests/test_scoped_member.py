"""The member floor, walked as a real actor (RADD-788).

The scenario is the live one that produced the bug: an admin empties the Baseline
role (RADD-773's setting), and a person's entire access is ONE role grant SCOPED
to a project — which is the normal shape of a grant on this instance, and which
contributes nothing at global scope.

Roughly 28 endpoints used to gate on `item.read` with no project as a stand-in for
"is this an ordinary member?". That check could not fail before RADD-773, because
`item.read` sat in the hardcoded MEMBER_FLOOR — so it was decoration, and the first
admin to empty the Baseline turned all of it into 403s for actual members.

This walks the HTTP surface with that person's own token and asserts the answer for
each endpoint, which is the only form of this test that cannot pass vacuously: a
service-level check would resolve the permissions correctly and never touch the
gate that was wrong.
"""

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth import grants, roles as roles_service
from radd.modules.auth.models import Role, User
from radd.modules.auth.schemas import RoleCreate, TokenCreate
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole, Permission
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

#: What "Studio Members" holds on the live instance — a read/comment/create role.
SCOPED_ROLE_ATOMS = [
    Permission.ITEM_READ,
    Permission.ITEM_CREATE,
    Permission.COMMENT_WRITE,
    Permission.PAGE_READ,
    Permission.VIEW_CREATE,
    # RADD-790 — deliberately WITHOUT item.update: this is a role that may
    # discuss an issue and attach to it without editing its fields, which is the
    # combination the old `item.update` attachment gate made impossible.
    Permission.ATTACHMENT_CREATE,
]


async def _bearer(session, user: User) -> str:
    from radd.modules.auth import service as auth_service

    _, raw = await auth_service.create_api_token(session, user, TokenCreate(name="walk"))
    return raw


@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("scoped-member-attachments")


@pytest.fixture(scope="module")
async def world(tmp_storage):
    """COMMITTED: the app under test opens its own session, so a rolled-back
    fixture would be invisible to it."""
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        baseline = (
            await session.execute(
                select(Role).where(Role.key == BuiltinRoleKey.BASELINE.value)
            )
        ).scalar_one()
        previous_baseline = list(baseline.permissions or [])
        baseline.permissions = []

        granted = await projects_service.create_project(
            session, ProjectCreate(key=f"GR{uuid.uuid4().hex[:4].upper()}", name="Granted")
        )
        withheld = await projects_service.create_project(
            session, ProjectCreate(key=f"WH{uuid.uuid4().hex[:4].upper()}", name="Withheld")
        )
        role = await roles_service.create_role(
            session,
            RoleCreate(
                key=f"scoped-{uuid.uuid4().hex[:6]}",
                name="Scoped Members",
                permissions=[p.value for p in SCOPED_ROLE_ATOMS],
            ),
        )
        member = User(
            email=f"scoped-{uuid.uuid4().hex[:8]}@example.com",
            name="Scoped Member",
            instance_role=InstanceRole.MEMBER.value,
        )
        stranger = User(
            email=f"stranger-{uuid.uuid4().hex[:8]}@example.com",
            name="Entitled To Nothing",
            instance_role=InstanceRole.MEMBER.value,
        )
        # A place for bytes to land. Without a default host the upload answers 409
        # about storage configuration, which would let the permission assertion
        # below pass or fail for a reason that has nothing to do with permissions.
        from radd.modules.attachments.models import StorageHost
        from radd.modules.attachments.types import StorageHostType

        session.add(
            StorageHost(
                name=f"proof-fs-{uuid.uuid4().hex[:6]}",
                host_type=StorageHostType.FILESYSTEM.value,
                root_dir=str(tmp_storage),
                is_default=True,
            )
        )
        session.add_all([member, stranger])
        await session.flush()
        # The ONLY thing this person holds, anywhere.
        await grants.create_grant(session, role.id, user_id=member.id, project_id=granted.id)

        payload = {
            "member_token": await _bearer(session, member),
            "stranger_token": await _bearer(session, stranger),
            "granted_id": str(granted.id),
            "granted_key": granted.key,
            "withheld_id": str(withheld.id),
        }
        await session.commit()
        yield payload

        # Put the Baseline back: the suite shares one database and a permanently
        # empty floor would silently change every later module's answers.
        baseline = (
            await session.execute(
                select(Role).where(Role.key == BuiltinRoleKey.BASELINE.value)
            )
        ).scalar_one()
        baseline.permissions = previous_baseline
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


#: Every surface the floor used to refuse. A project-scoped member reaches all of
#: them; the ids are formatted in per test.
FLOOR_PATHS = [
    "/api/v1/views",
    "/api/v1/views?project_id={granted_id}",
    "/api/v1/views/card-presets",
    "/api/v1/cycles",
    "/api/v1/cycle-series",
    "/api/v1/labels",
    "/api/v1/roles",
    "/api/v1/permissions",
    "/api/v1/teams",
    "/api/v1/fields",
    "/api/v1/dashboards",
    "/api/v1/events",
    "/api/v1/work-categories",
    "/api/v1/canned-responses",
    "/api/v1/automations/runnable",
    "/api/v1/timesheet?start=2026-08-01&end=2026-08-03",
    "/api/v1/projects",
    "/api/v1/items",
    "/api/v1/items?project_id={granted_id}",
]


async def test_project_scoped_member_reaches_every_floor_surface(client, world):
    """The regression. Each of these answered 403 'item.read denied' before."""
    failures = []
    for template in FLOOR_PATHS:
        path = template.format(**world)
        response = await client.get(path, headers=_auth(world["member_token"]))
        if response.status_code != 200:
            failures.append(f"{path} -> {response.status_code} {response.text[:120]}")
    assert not failures, "floor surfaces refused a project-scoped member:\n" + "\n".join(
        failures
    )


async def test_the_board_is_reachable(client, world):
    """The symptom that started this: views are the only way into a project since
    specs 61-67 deleted the builtin board/list/planning pages, so a refused view
    list leaves a project containing nothing."""
    response = await client.get(
        f"/api/v1/views?project_id={world['granted_id']}",
        headers=_auth(world["member_token"]),
    )
    assert response.status_code == 200
    assert response.json(), "the seeded project views should be visible"


async def test_the_grant_still_bounds_what_is_visible(client, world):
    """The floor must not have become a skeleton key: the project this person was
    NOT granted stays invisible, and its items stay unreadable."""
    projects = (
        await client.get("/api/v1/projects", headers=_auth(world["member_token"]))
    ).json()
    visible = {p["id"] for p in projects}
    assert world["granted_id"] in visible
    assert world["withheld_id"] not in visible

    items = await client.get(
        f"/api/v1/items?project_id={world['withheld_id']}",
        headers=_auth(world["member_token"]),
    )
    assert items.status_code == 403


async def test_entitled_to_nothing_gets_emptiness_not_a_wall_of_errors(client, world):
    """RADD-774's rule, applied to the whole class: a person granted nothing
    anywhere is not doing anything wrong, so list surfaces answer empty rather
    than refusing. A new SSO account landing on a screen of permission toasts is
    the failure this replaces."""
    listing = [
        "/api/v1/views",
        "/api/v1/labels",
        "/api/v1/cycles",
        "/api/v1/fields",
        "/api/v1/dashboards",
        "/api/v1/roles",
        "/api/v1/teams",
        "/api/v1/projects",
        "/api/v1/work-categories",
        "/api/v1/canned-responses",
    ]
    for path in listing:
        response = await client.get(path, headers=_auth(world["stranger_token"]))
        assert response.status_code == 200, f"{path} -> {response.status_code}"
        assert response.json() == [], f"{path} leaked rows to an unentitled actor"


async def test_a_commenter_can_attach_the_file_they_are_describing(client, world):
    """RADD-790. `item.read` + `comment.write` + `attachment.create` is a role
    that may discuss an issue without editing it. Attaching used to demand
    `item.update`, so the comment posted (201) and the pasted screenshot 403'd —
    which is why this was reported as "commenting is broken"."""
    item = await client.post(
        "/api/v1/items",
        headers=_auth(world["member_token"]),
        json={"project_id": world["granted_id"], "title": "Attach target"},
    )
    assert item.status_code == 201, item.text
    item_id = item.json()["id"]

    comment = await client.post(
        f"/api/v1/items/{item_id}/comments",
        headers=_auth(world["member_token"]),
        json={"body": "the log is attached"},
    )
    assert comment.status_code == 201

    upload = await client.post(
        "/api/v1/attachments",
        headers=_auth(world["member_token"]),
        files={"file": ("crash.log", b"segfault", "text/plain")},
        data={"entity_type": "item", "entity_id": item_id},
    )
    assert upload.status_code == 201, (
        "a commenter could not attach the file they were describing: " + upload.text
    )


async def test_attaching_is_still_gated(client, world):
    """The split is not a hole: an actor with no access to the project still
    cannot attach to its items."""
    item = await client.post(
        "/api/v1/items",
        headers=_auth(world["member_token"]),
        json={"project_id": world["granted_id"], "title": "Not yours"},
    )
    upload = await client.post(
        "/api/v1/attachments",
        headers=_auth(world["stranger_token"]),
        files={"file": ("x.txt", b"x", "text/plain")},
        data={"entity_type": "item", "entity_id": item.json()["id"]},
    )
    assert upload.status_code == 403


async def test_cross_project_reports_cover_only_readable_projects(client, world):
    """RADD-789. The SLA report used to fold EVERY project's bookkeeping rows into
    its averages whenever no SLQ `q` was passed — the global item.read gate was
    the only thing in front of it, and RADD-788 relaxed that gate.

    The figure now carries the scope it was computed over, so a filtered average
    is never silently a different number.
    """
    response = await client.get("/api/v1/reports/velocity", headers=_auth(world["member_token"]))
    assert response.status_code == 200
    scope = response.json()["scope"]
    assert scope["covered"] == [world["granted_key"]], "velocity reached past the grant"
    assert scope["total"] > len(scope["covered"]), "the fixture needs an unreadable project"

    sla = await client.get("/api/v1/reports/sla", headers=_auth(world["member_token"]))
    assert sla.status_code == 200
    assert sla.json()["scope"]["covered"] == [world["granted_key"]]


async def test_single_resource_reads_still_refuse_the_unentitled(client, world):
    """Where emptiness is not an available answer, the refusal stays — a cycle
    either comes back or it does not."""
    response = await client.get("/api/v1/events", headers=_auth(world["stranger_token"]))
    assert response.status_code == 403
