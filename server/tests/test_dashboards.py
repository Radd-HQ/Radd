"""Composable dashboards (spec 75) — sharing/visibility parity with views
(spec 57: owner sees, outsider 404s, global_access floor, editor edits but
never re-shares, transfer keeps the old owner as editor), widget config
validation (SLQ 422 w/ position, invisible view 409, width/type 422), and
GET /items/count matching /items/ids totals under visibility. Rolled-back
transactions on the compose DB."""

import uuid

import pydantic
import pytest

from radd.modules.access import service as access_service
from radd.modules.access.types import GrantSubject
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.dashboards import service as dashboards, widgets as dashboard_widgets
from radd.modules.dashboards.schemas import (
    DashboardCreate,
    DashboardShareEntry,
    DashboardSharingUpdate,
    DashboardTransfer,
    DashboardUpdate,
    SlqCountConfig,
    SlqCountWidget,
    ViewCountConfig,
    ViewCountWidget,
    WidgetCreate,
    WidgetUpdate,
)
from radd.modules.dashboards.types import ShareLevel, WidgetType
from radd.modules.items import bulk, service as items_service
from radd.modules.items.enums import Priority
from radd.modules.items.filters import ItemListFilters
from radd.modules.items.schemas import ItemCreate
from radd.modules.items.slq import SlqError
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate
from radd.modules.views import service as views_service
from radd.modules.views.schemas import ViewCreate
from radd.modules.views.types import ViewType
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
        email=f"dash-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=instance_role.value,
    )
    db.add(user)
    await db.flush()
    return user


def _slq_count_widget(q="", **kwargs) -> SlqCountWidget:
    return SlqCountWidget(
        widget_type=WidgetType.SLQ_COUNT,
        config=SlqCountConfig(q=q),
        **kwargs,
    )


async def test_dashboard_sharing_matrix(db):
    owner = await _member(db, "Owner")
    direct = await _member(db, "Direct Grantee")
    teammate = await _member(db, "Team Grantee")
    outsider = await _member(db, "Outsider")
    admin = await _member(db, "Admin", instance_role=InstanceRole.ADMIN)
    team = await teams_service.create_team(db, TeamCreate(name=f"FX-{uuid.uuid4().hex[:6]}"))
    await teams_service.add_team_member(db, team.id, teammate.id)

    async def visible_names(actor) -> set[str]:
        reads = await dashboards.list_dashboards(db, actor=actor)
        return {r.name for r in reads}

    created = await dashboards.create_dashboard(
        db,
        DashboardCreate(
            name="Delivery",
            shares=[
                DashboardShareEntry(user_id=direct.id, level=ShareLevel.VIEWER),
                DashboardShareEntry(team_id=team.id, level=ShareLevel.EDITOR),
            ],
        ),
        actor=owner,
    )
    assert created.owner_id == owner.id and created.shared and created.can_manage

    # Visibility: owner + grantees see it; everyone else — ADMINS INCLUDED —
    # gets a 404 (not shared = it does not exist for you).
    assert "Delivery" in await visible_names(owner)
    assert "Delivery" in await visible_names(direct)
    assert "Delivery" in await visible_names(teammate)
    assert "Delivery" not in await visible_names(outsider)
    with pytest.raises(NotFoundError):
        await dashboards.get_dashboard_read(db, created.id, actor=outsider)
    with pytest.raises(NotFoundError):
        await dashboards.get_dashboard_read(db, created.id, actor=admin)

    # Levels: the viewer can't edit (403 — visible, so not a 404)…
    with pytest.raises(ForbiddenError):
        await dashboards.update_dashboard(
            db, created.id, DashboardUpdate(name="nope"), actor=direct
        )
    # …the team-granted editor edits the definition AND writes widgets…
    renamed = await dashboards.update_dashboard(
        db, created.id, DashboardUpdate(name="Team Delivery"), actor=teammate
    )
    assert renamed.name == "Team Delivery" and renamed.can_edit and not renamed.can_manage
    with_widget = await dashboard_widgets.create_widget(
        db, created.id, _slq_count_widget(), actor=teammate
    )
    assert len(with_widget.widgets) == 1
    # …but neither re-shares nor deletes — that's the owner's (and viewers
    # can't touch widgets at all).
    with pytest.raises(ForbiddenError):
        await dashboards.update_sharing(
            db, created.id, DashboardSharingUpdate(shares=[]), actor=teammate
        )
    with pytest.raises(ForbiddenError):
        await dashboards.delete_dashboard(db, created.id, actor=teammate)
    with pytest.raises(ForbiddenError):
        await dashboard_widgets.create_widget(
            db, created.id, _slq_count_widget(), actor=direct
        )

    # Owner revokes the team grant; the teammate loses the dashboard entirely.
    # Per-subject sharing is the generic /grants API now (spec 92 adopters) —
    # PUT /sharing only carries `global_access`, mirroring views.
    grants = await access_service.list_for_resource(db, "dashboard", str(created.id))
    team_grant = next(g for g in grants if g.subject_id == team.id)
    await access_service.remove_grant(db, team_grant.id)
    # …and upgrades the direct grantee to editor (max level wins).
    await access_service.add_grant(
        db,
        "dashboard",
        str(created.id),
        subject_type=GrantSubject.USER,
        subject_id=direct.id,
        access=ShareLevel.EDITOR.value,
    )
    assert "Team Delivery" not in await visible_names(teammate)
    # Managing share grants is gated by the ResourceSpec hook the /grants router uses.
    assert await dashboards._can_manage_dashboard(db, owner, str(created.id), None)
    assert not await dashboards._can_manage_dashboard(db, teammate, str(created.id), None)

    # Global broadcast is gated: a plain member lacks dashboard.create.
    with pytest.raises(ForbiddenError):
        await dashboards.update_sharing(
            db,
            created.id,
            DashboardSharingUpdate(global_access=ShareLevel.VIEWER),
            actor=owner,
        )
    # global_access can never be 'owner' (anyone could delete/transfer).
    with pytest.raises(ConflictError):
        await dashboards.update_sharing(
            db, created.id, DashboardSharingUpdate(global_access=ShareLevel.OWNER), actor=owner
        )

    # An instance ADMIN can broadcast; every active user then gets the viewer
    # floor: visible to everyone, editable by no one but the owner.
    broadcast = await dashboards.create_dashboard(
        db,
        DashboardCreate(name="Everyone", global_access=ShareLevel.VIEWER),
        actor=admin,
    )
    assert "Everyone" in await visible_names(outsider)
    with pytest.raises(ForbiddenError):
        await dashboards.update_dashboard(
            db, broadcast.id, DashboardUpdate(name="hijack"), actor=outsider
        )


async def test_transfer_keeps_previous_owner_as_editor(db):
    owner = await _member(db, "Original Owner")
    heir = await _member(db, "Heir")
    stranger = User(  # spec 86: only an INACTIVE user is barred from receiving
        email=f"dt-{uuid.uuid4().hex[:8]}@example.com",
        name="Stranger",
        instance_role=InstanceRole.MEMBER.value,
        active=False,
    )
    db.add(stranger)
    await db.flush()

    created = await dashboards.create_dashboard(
        db, DashboardCreate(name="Handover"), actor=owner
    )
    # Transfer to a deactivated user 409s (they can't use dashboards at all).
    with pytest.raises(ConflictError):
        await dashboards.transfer_ownership(
            db, created.id, DashboardTransfer(user_id=stranger.id), actor=owner
        )

    transferred = await dashboards.transfer_ownership(
        db, created.id, DashboardTransfer(user_id=heir.id), actor=owner
    )
    assert transferred.owner_id == heir.id
    as_old_owner = await dashboards.get_dashboard_read(db, created.id, actor=owner)
    assert as_old_owner.can_edit and not as_old_owner.can_manage
    with pytest.raises(ForbiddenError):
        await dashboards.delete_dashboard(db, created.id, actor=owner)
    as_heir = await dashboards.get_dashboard_read(db, created.id, actor=heir)
    assert as_heir.can_manage
    assert all(s.user is None or s.user.id != heir.id for s in as_heir.shares)


async def test_widget_config_validation(db):
    owner = await _member(db, "Widget Owner")
    other = await _member(db, "Private View Owner")
    dashboard = await dashboards.create_dashboard(
        db, DashboardCreate(name="Board"), actor=owner
    )

    # Bad SLQ → the spec-10 SlqError (422 {detail, position} on the wire).
    with pytest.raises(SlqError) as exc:
        await dashboard_widgets.create_widget(
            db, dashboard.id, _slq_count_widget(q="priority ="), actor=owner
        )
    assert isinstance(exc.value.position, int)

    # view_count on a view the WRITER can't see → 409 (not a silent dangle).
    private_view = await views_service.create_view(
        db,
        ViewCreate(name="Mine", view_type=ViewType.LIST),
        actor=other,
    )
    with pytest.raises(ConflictError):
        await dashboard_widgets.create_widget(
            db,
            dashboard.id,
            ViewCountWidget(
                widget_type=WidgetType.VIEW_COUNT,
                config=ViewCountConfig(view_id=private_view.id),
            ),
            actor=owner,
        )

    # Width bounds + unknown types are pydantic 422s at the boundary.
    with pytest.raises(pydantic.ValidationError):
        _slq_count_widget(width=4)
    with pytest.raises(pydantic.ValidationError):
        pydantic.TypeAdapter(WidgetCreate).validate_python(
            {"widget_type": "sparkline", "config": {}}
        )

    # Happy path + PATCH: config revalidates against the STORED type.
    read = await dashboard_widgets.create_widget(
        db,
        dashboard.id,
        _slq_count_widget(q="priority = blocker", title="Blockers", width=2),
        actor=owner,
    )
    widget = read.widgets[0]
    assert widget.widget_type is WidgetType.SLQ_COUNT and widget.width == 2
    assert widget.config["q"] == "priority = blocker"
    # The PATCH still revalidates against the stored type (bad SLQ → spec-10 422).
    with pytest.raises(SlqError):
        await dashboard_widgets.update_widget(
            db, dashboard.id, widget.id, WidgetUpdate(config={"q": "x"}), actor=owner
        )
    patched = await dashboard_widgets.update_widget(
        db,
        dashboard.id,
        widget.id,
        WidgetUpdate(width=3, config={"q": ""}),
        actor=owner,
    )
    assert patched.widgets[0].width == 3 and patched.widgets[0].config["q"] == ""


async def test_items_count_matches_ids_total_under_visibility(db):
    run = uuid.uuid4().hex[:8]
    seeder = await _member(db, "Seeder", instance_role=InstanceRole.ADMIN)
    away_seeder = await _member(db, "Away Seeder", instance_role=InstanceRole.ADMIN)
    actor = await _member(db, "Counter")  # a plain active member
    home_project = await projects_service.create_project(
        db,
        ProjectCreate(key=f"DC{run[:4].upper()}", name="Home"),
    )
    away_project = await projects_service.create_project(
        db,
        ProjectCreate(key=f"DA{run[:4].upper()}", name="Away"),
    )
    for index, priority in enumerate((Priority.BLOCKER, Priority.BLOCKER, Priority.LOW)):
        await items_service.create_item(
            db,
            ItemCreate(project_id=home_project.id, title=f"c-{index}", priority=priority),
            seeder,
        )
    await items_service.create_item(
        db, ItemCreate(project_id=away_project.id, title="invisible"), away_seeder
    )

    # Spec 86: every ACTIVE user reads every project, so pin the deterministic
    # numbers on a project filter — the invariant under test is count/ids
    # PARITY, exercised against the same visibility path.
    filters = ItemListFilters(project_id=home_project.id)
    ids = await bulk.list_item_ids(db, actor=actor, filters=filters)
    assert await bulk.count_items(db, actor=actor, filters=filters) == ids.total == 3

    # SLQ narrows both the same way.
    q = "priority = blocker"
    ids = await bulk.list_item_ids(db, actor=actor, filters=filters, q=q)
    assert await bulk.count_items(db, actor=actor, filters=filters, q=q) == ids.total == 2

    # And unfiltered parity holds instance-wide (no magic totals: live DB).
    unfiltered = ItemListFilters()
    ids = await bulk.list_item_ids(db, actor=actor, filters=unfiltered)
    assert await bulk.count_items(db, actor=actor, filters=unfiltered) == ids.total >= 4
