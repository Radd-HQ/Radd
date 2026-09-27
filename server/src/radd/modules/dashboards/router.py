import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.apitypes import TOTAL_COUNT_HEADER
from radd.modules.auth.deps import CurrentUser

from . import directory, service, widgets
from .widget_bodies import parse_widget_body
from .schemas import (
    DashboardCreate,
    DashboardSave,
    DashboardRead,
    DashboardSharingUpdate,
    DashboardTransfer,
    DashboardUpdate,
    WidgetUpdate,
    WidgetLayoutSave,
    WidgetRead,
)

router = APIRouter(prefix="/dashboards", tags=["dashboards"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=DashboardRead, status_code=201)
async def create_dashboard(
    data: DashboardCreate, session: Session, user: CurrentUser
) -> DashboardRead:
    return await service.create_dashboard(session, data, actor=user)


@router.get("", response_model=list[DashboardRead])
async def list_dashboards(
    session: Session,
    user: CurrentUser,
    response: Response,
    include_shares: bool = True,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DashboardRead]:
    """Dashboards the actor can SEE (spec-57 visibility), ordered position→name."""
    rows, total = await service.page_dashboards(
        session, actor=user, include_shares=include_shares, q=q, limit=limit, offset=offset
    )
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@router.get("/summary", response_model=dict[str, int])
async def dashboard_summary(
    session: Session,
    user: CurrentUser,
    q: Annotated[str, Query(max_length=200)] = "",
) -> dict[str, int]:
    return {"total": await directory.count(session, user, q=q)}


@router.get("/my-work/widgets", response_model=list[WidgetRead])
async def my_work_widgets(session: Session, user: CurrentUser):
    from . import personal

    if "my_work_widgets" in (user.preferences or {}):
        return personal.read(user)
    return await personal.suggested_defaults(session, user)


@router.put("/my-work/widgets", response_model=list[WidgetRead])
async def save_my_work_widgets(data: WidgetLayoutSave, session: Session, user: CurrentUser):
    from . import personal

    return await personal.save(session, user, data)


@router.get("/my-work/defaults", response_model=list[WidgetRead])
async def my_work_defaults(session: Session, user: CurrentUser):
    from .personal import suggested_defaults

    return await suggested_defaults(session, user)


@router.get("/my-work/activity")
async def my_activity(
    session: Session,
    user: CurrentUser,
    before: int | None = None,
    project_id: uuid.UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(10, ge=1, le=50),
):
    from . import activity

    return await activity.read(
        session, user, before=before, project_id=project_id, start=start, end=end, limit=limit
    )


@router.get("/{dashboard_id}", response_model=DashboardRead)
async def get_dashboard(
    dashboard_id: uuid.UUID, session: Session, user: CurrentUser, include_shares: bool = True
) -> DashboardRead:
    """The full definition incl. widgets + per-actor can_edit/can_manage."""
    return await service.get_dashboard_read(
        session, dashboard_id, actor=user, include_shares=include_shares
    )


@router.patch("/{dashboard_id}", response_model=DashboardRead)
async def update_dashboard(
    dashboard_id: uuid.UUID, data: DashboardUpdate, session: Session, user: CurrentUser
) -> DashboardRead:
    return await service.update_dashboard(session, dashboard_id, data, actor=user)


_SHARING_DOC = (
    "Set the dashboard's PUBLIC access level: global_access (what every active user gets; "
    "null = not globally visible; never 'owner' → 409). Owner/co-owner only; enabling "
    "global_access needs dashboard.create. Per-user/team grants moved to the generic "
    "/grants API (spec 92) — resource_type 'dashboard'."
)


@router.put("/{dashboard_id}/sharing", response_model=DashboardRead, description=_SHARING_DOC)
async def update_sharing(
    dashboard_id: uuid.UUID, data: DashboardSharingUpdate, session: Session, user: CurrentUser
) -> DashboardRead:
    return await service.update_sharing(session, dashboard_id, data, actor=user)


_TRANSFER_DOC = (
    "Reassign the dashboard's owner. Owner/co-owner only; the target must be an active user "
    "(409 otherwise). The previous owner stays on as an editor grantee."
)


@router.post("/{dashboard_id}/transfer", response_model=DashboardRead, description=_TRANSFER_DOC)
async def transfer_dashboard(
    dashboard_id: uuid.UUID, data: DashboardTransfer, session: Session, user: CurrentUser
) -> DashboardRead:
    return await service.transfer_ownership(session, dashboard_id, data, actor=user)


@router.delete("/{dashboard_id}", status_code=204)
async def delete_dashboard(dashboard_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await service.delete_dashboard(session, dashboard_id, actor=user)


_WIDGET_DOC = (
    "Add a widget (owner/editor). A builtin widget_type is a discriminated union whose config is "
    "validated per type — bad SLQ → 422 {detail, position}, broken project/cycle/view "
    "references → 409; a plugin-contributed widget_type (registries.widget_types) carries a "
    "free-form config dict. Unknown types → 422. Returns the full updated dashboard."
)

@router.post(
    "/{dashboard_id}/widgets",
    response_model=DashboardRead,
    status_code=201,
    description=_WIDGET_DOC,
)
async def create_widget(
    dashboard_id: uuid.UUID,
    body: Annotated[dict[str, Any], Body(...)],
    session: Session,
    user: CurrentUser,
) -> DashboardRead:
    return await widgets.create_widget(session, dashboard_id, parse_widget_body(body), actor=user)


@router.patch("/{dashboard_id}/widgets/{widget_id}", response_model=DashboardRead)
async def update_widget(
    dashboard_id: uuid.UUID,
    widget_id: uuid.UUID,
    data: WidgetUpdate,
    session: Session,
    user: CurrentUser,
) -> DashboardRead:
    """Patch title/width/position/config (owner/editor). A new config revalidates
    against the widget's stored type; widget_type itself is immutable."""
    return await widgets.update_widget(session, dashboard_id, widget_id, data, actor=user)


@router.delete("/{dashboard_id}/widgets/{widget_id}", status_code=204)
async def delete_widget(
    dashboard_id: uuid.UUID, widget_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    await widgets.delete_widget(session, dashboard_id, widget_id, actor=user)


@router.post("/{dashboard_id}/save", response_model=DashboardRead)
async def save_dashboard(
    dashboard_id: uuid.UUID, data: DashboardSave, session: Session, user: CurrentUser
) -> DashboardRead:
    return await service.save_dashboard(session, dashboard_id, data, actor=user)


@router.put("/{dashboard_id}/widgets", response_model=DashboardRead)
async def replace_widgets(
    dashboard_id: uuid.UUID, data: WidgetLayoutSave, session: Session, user: CurrentUser
):
    return await widgets.replace_widgets(session, dashboard_id, data, parse_widget_body, actor=user)
