"""View ownership + sharing (spec 57) — the access matrix everything hangs on:
visibility (owner / direct grantee / team grantee / global_access; others
404), edit levels (editor edits, viewer doesn't), owner-only share management,
and the global-broadcast gate. Plus spec 64: queue-type acceptance and the
batched counts endpoint (visibility-filtered, compiled-SLQ correctness).
Rolled-back transactions on the compose DB."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ForbiddenError, NotFoundError
from radd.modules.access import service as access_service
from radd.modules.access.types import GrantSubject
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate
from radd.modules.items import service as items_service
from radd.modules.items.enums import Priority
from radd.modules.items.schemas import ItemCreate
from radd.modules.views import counts as views_counts, service as views_service
from radd.modules.views.models import View
from radd.modules.views.schemas import (
    ViewCreate,
    ViewShareEntry,
    ViewSharingUpdate,
    ViewTransfer,
    ViewUpdate,
)
from radd.modules.views.types import ShareLevel, ViewType
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _member(db, name, *, instance_role=InstanceRole.MEMBER) -> User:
    """An active user — active users hold the global member floor (spec 86);
    instance_role=ADMIN is the global admin."""
    user = User(
        email=f"vs-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=instance_role.value,
    )
    db.add(user)
    await db.flush()
    return user


async def test_view_sharing_matrix(db):
    owner = await _member(db, "Owner")
    direct = await _member(db, "Direct Grantee")
    teammate = await _member(db, "Team Grantee")
    outsider = await _member(db, "Outsider")
    team = await teams_service.create_team(db, TeamCreate(name=f"FX-{uuid.uuid4().hex[:6]}"))
    await teams_service.add_team_member(db, team.id, teammate.id)

    async def visible_names(actor) -> set[str]:
        reads = await views_service.list_views(db, actor=actor, project_id=None)
        return {r.name for r in reads}

    # A plain member creates a view shared at birth: direct viewer + team editor.
    created = await views_service.create_view(
        db,
        ViewCreate(
            name="Owner board",
            view_type=ViewType.BOARD,
            shares=[
                ViewShareEntry(user_id=direct.id, level=ShareLevel.VIEWER),
                ViewShareEntry(team_id=team.id, level=ShareLevel.EDITOR),
            ],
        ),
        actor=owner,
    )
    assert created.owner_id == owner.id and created.shared and created.can_manage

    # Visibility: owner + grantees see it; the outsider doesn't even know it exists.
    assert "Owner board" in await visible_names(owner)
    assert "Owner board" in await visible_names(direct)
    assert "Owner board" in await visible_names(teammate)
    assert "Owner board" not in await visible_names(outsider)
    with pytest.raises(NotFoundError):
        await views_service.update_view(db, created.id, ViewUpdate(name="hijack"), actor=outsider)

    # Levels: the viewer can't edit (403 — visible, so not a 404)…
    with pytest.raises(ForbiddenError):
        await views_service.update_view(db, created.id, ViewUpdate(name="nope"), actor=direct)
    # …the team-granted editor can edit the definition…
    renamed = await views_service.update_view(
        db, created.id, ViewUpdate(name="Team renamed"), actor=teammate
    )
    assert renamed.name == "Team renamed" and renamed.can_edit and not renamed.can_manage
    # …but neither re-shares nor deletes — that's the owner's. Managing a view's share
    # GRANTS is gated by `_can_manage_view` (the /grants router's hook); the editor fails.
    assert not await views_service._can_manage_view(db, teammate, str(created.id), None)
    assert await views_service._can_manage_view(db, owner, str(created.id), None)
    with pytest.raises(ForbiddenError):
        await views_service.delete_view(db, created.id, actor=teammate)

    # Owner revokes the team grant; the teammate loses the view entirely.
    grants = await access_service.list_for_resource(db, "view", str(created.id))
    team_grant = next(g for g in grants if g.subject_id == team.id)
    await access_service.remove_grant(db, team_grant.id)
    # …and upgrades the direct grantee to editor (max level wins).
    await access_service.add_grant(
        db, "view", str(created.id),
        subject_type=GrantSubject.USER, subject_id=direct.id, access=ShareLevel.EDITOR.value,
    )
    assert "Team renamed" not in await visible_names(teammate)
    # The direct grantee got upgraded to editor and can now edit.
    upgraded = await views_service.update_view(
        db, created.id, ViewUpdate(name="Direct renamed"), actor=direct
    )
    assert upgraded.can_edit

    # Global broadcast is gated: a plain member lacks view.create.
    with pytest.raises(ForbiddenError):
        await views_service.update_sharing(
            db,
            created.id,
            ViewSharingUpdate(global_access=ShareLevel.VIEWER),
            actor=owner,
        )

    # LEGACY owner-less views: visible to every active user, RBAC atoms manage them.
    legacy = View(
        name="Legacy shared",
        view_type=ViewType.LIST.value,
        query="",
        owner_id=None,
        global_access=ShareLevel.VIEWER.value,
    )
    db.add(legacy)
    await db.flush()
    assert "Legacy shared" in await visible_names(outsider)
    with pytest.raises(ForbiddenError):
        await views_service.update_view(db, legacy.id, ViewUpdate(name="no"), actor=outsider)
    admin = await _member(db, "Admin", instance_role=InstanceRole.ADMIN)
    kept = await views_service.update_view(
        db, legacy.id, ViewUpdate(name="Legacy kept"), actor=admin
    )
    assert kept.name == "Legacy kept" and kept.can_manage


async def test_co_ownership_and_transfer(db):
    from radd.exceptions import ConflictError

    owner = await _member(db, "Original Owner")
    coowner = await _member(db, "Co Owner")
    heir = await _member(db, "Heir")
    stranger = User(  # spec 86: only an INACTIVE user is barred from receiving
        email=f"vt-{uuid.uuid4().hex[:8]}@example.com", name="Stranger",
        instance_role=InstanceRole.MEMBER.value, active=False,
    )
    db.add(stranger)
    await db.flush()

    view = await views_service.create_view(
        db,
        ViewCreate(
            name="Handover board",
            view_type=ViewType.BOARD,
            shares=[ViewShareEntry(user_id=coowner.id, level=ShareLevel.OWNER)],
        ),
        actor=owner,
    )
    # Co-owner (owner-level grantee): full control — edit, re-share…
    read = next(
        r
        for r in await views_service.list_views(db, actor=coowner, project_id=None)
        if r.id == view.id
    )
    assert read.can_edit and read.can_manage
    # A co-owner can add a share grant (the /grants router would allow it — the gate
    # is `_can_manage_view`, True for an OWNER-level grantee).
    assert await views_service._can_manage_view(db, coowner, str(view.id), None)
    await access_service.add_grant(
        db, "view", str(view.id),
        subject_type=GrantSubject.USER, subject_id=heir.id, access=ShareLevel.VIEWER.value,
    )

    # global_access can never be 'owner' (anyone could delete/transfer).
    with pytest.raises(ConflictError):
        await views_service.update_sharing(
            db, view.id, ViewSharingUpdate(global_access=ShareLevel.OWNER), actor=owner
        )
    # Transfer to a deactivated user 409s (they can't use views at all).
    with pytest.raises(ConflictError):
        await views_service.transfer_ownership(
            db, view.id, ViewTransfer(user_id=stranger.id), actor=owner
        )

    # Transfer to the heir: owner_id moves, heir's old grant is dropped, the
    # previous owner stays on as editor (can edit, can't manage).
    transferred = await views_service.transfer_ownership(
        db, view.id, ViewTransfer(user_id=heir.id), actor=owner
    )
    assert transferred.owner_id == heir.id
    as_old_owner = next(
        r
        for r in await views_service.list_views(db, actor=owner, project_id=None)
        if r.id == view.id
    )
    assert as_old_owner.can_edit and not as_old_owner.can_manage
    with pytest.raises(ForbiddenError):
        await views_service.delete_view(db, view.id, actor=owner)
    # The heir has full control now (and no lingering share row for themselves).
    as_heir = next(
        r
        for r in await views_service.list_views(db, actor=heir, project_id=None)
        if r.id == view.id
    )
    assert as_heir.can_manage
    assert all(s.user is None or s.user.id != heir.id for s in as_heir.shares)


async def test_queue_type_and_view_counts(db):
    """Spec 64: QUEUE is a first-class ViewType, and POST /views/counts returns
    compiled-SLQ counts for exactly the views the actor can see (invisible and
    unknown ids omitted, never errored)."""
    owner = await _member(db, "Queue Owner")
    grantee = await _member(db, "Count Grantee")
    outsider = await _member(db, "Count Outsider")
    # Plain members hold the read-only project floor — an admin seeds the items.
    seeder = await _member(db, "Item Seeder", instance_role=InstanceRole.ADMIN)
    project = await projects_service.create_project(
        db,
        ProjectCreate(key=f"VQ{uuid.uuid4().hex[:4].upper()}", name="Desk"),
    )
    for index, priority in enumerate((Priority.BLOCKER, Priority.BLOCKER, Priority.LOW)):
        await items_service.create_item(
            db, ItemCreate(project_id=project.id, title=f"q-{index}", priority=priority), seeder
        )

    # Queue-type acceptance: created like any view; axes stored but unused.
    queue = await views_service.create_view(
        db,
        ViewCreate(
            project_id=project.id,
            name="Blockers queue",
            view_type=ViewType.QUEUE,
            query="priority = blocker",
            group_by="state",
        ),
        actor=owner,
    )
    assert queue.view_type == ViewType.QUEUE  # ViewRead.view_type is now a str
    everything = await views_service.create_view(
        db,
        ViewCreate(
            project_id=project.id,
            name="All open",
            view_type=ViewType.QUEUE,
            shares=[ViewShareEntry(user_id=grantee.id, level=ShareLevel.VIEWER)],
        ),
        actor=owner,
    )

    # Owner sees both counts; the seeded query narrows to the 2 blockers, the
    # empty-query view counts every item in the project; unknown id omitted.
    result = await views_counts.view_counts(
        db, actor=owner, view_ids=[queue.id, everything.id, uuid.uuid4()]
    )
    assert result == {queue.id: 2, everything.id: 3}

    # The grantee sees only the shared view; the outsider sees neither — both
    # get invisible ids OMITTED (no error), exactly like the read path.
    assert await views_counts.view_counts(
        db, actor=grantee, view_ids=[queue.id, everything.id]
    ) == {everything.id: 3}
    assert (
        await views_counts.view_counts(db, actor=outsider, view_ids=[queue.id, everything.id])
        == {}
    )


async def test_projects_ship_with_default_views(db):
    """Every project gets four PLAIN seeded views (Board/List/Planning/Roadmap)
    from the project-created hook — ordinary views: globally visible, editable
    via the view.* atoms, and deletable like any other (no special designation)."""
    run = uuid.uuid4().hex[:8]
    admin = await _member(db, "Admin", instance_role=InstanceRole.ADMIN)
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"VD{run[:4].upper()}", name="Defaults")
    )

    seeded = await views_service.list_views(db, actor=admin, project_id=project.id)
    assert {(v.name, v.view_type) for v in seeded} == {
        ("Board", "board"),
        ("List", "list"),
        ("Planning", "planning"),
        ("Roadmap", "roadmap"),
    }
    board = next(v for v in seeded if v.name == "Board")
    assert board.global_access is ShareLevel.VIEWER  # visible to every active user
    assert board.owner_id is None and board.can_manage  # admin edits via view.* atoms
    assert board.group_by == "state"

    # Just a view: rename it, or delete it outright — nothing is protected.
    renamed = await views_service.update_view(
        db, board.id, ViewUpdate(name="Kanban"), actor=admin
    )
    assert renamed.name == "Kanban"
    await views_service.delete_view(db, next(v.id for v in seeded if v.name == "List"), actor=admin)
    remaining = await views_service.list_views(db, actor=admin, project_id=project.id)
    assert {v.name for v in remaining} == {"Kanban", "Planning", "Roadmap"}
