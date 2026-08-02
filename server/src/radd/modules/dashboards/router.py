import uuid
from typing import Annotated, Any

import pydantic
from fastapi import APIRouter, Body, Depends
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.kernel import registries
from radd.modules.auth.deps import CurrentUser

from . import service, widgets
from .schemas import (
    DashboardCreate,
    DashboardRead,
    DashboardSharingUpdate,
    DashboardTransfer,
    DashboardUpdate,
    PluginWidget,
    WidgetCreate,
    WidgetUpdate,
)
from .types import WidgetType

router = APIRouter(prefix="/dashboards", tags=["dashboards"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=DashboardRead, status_code=201)
async def create_dashboard(
    data: DashboardCreate, session: Session, user: CurrentUser
) -> DashboardRead:
    return await service.create_dashboard(session, data, actor=user)


@router.get("", response_model=list[DashboardRead])
async def list_dashboards(session: Session, user: CurrentUser) -> list[DashboardRead]:
    """Dashboards the actor can SEE (spec-57 visibility), ordered position→name."""
    return await service.list_dashboards(session, actor=user)


@router.get("/{dashboard_id}", response_model=DashboardRead)
async def get_dashboard(
    dashboard_id: uuid.UUID, session: Session, user: CurrentUser
) -> DashboardRead:
    """The full definition incl. widgets + per-actor can_edit/can_manage."""
    return await service.get_dashboard_read(session, dashboard_id, actor=user)


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

_BUILTIN_WIDGET_TYPES = frozenset(t.value for t in WidgetType)


def _parse_widget_body(body: dict[str, Any]) -> WidgetCreate | PluginWidget:
    """Dispatch a raw widget-create body to its schema: a builtin widget_type
    validates against the discriminated union (typed per-type config); a type
    registered in registries.widget_types validates as a free-form PluginWidget;
    anything else is unknown → 422. A pydantic shape failure is surfaced as the
    same RequestValidationError (422) FastAPI would have raised for the body."""
    widget_type = body.get("widget_type")
    try:
        if widget_type in _BUILTIN_WIDGET_TYPES:
            return pydantic.TypeAdapter(WidgetCreate).validate_python(body)
        if isinstance(widget_type, str) and widget_type in registries.widget_types:
            return PluginWidget.model_validate(body)
    except pydantic.ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    raise RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", "widget_type"),
                "msg": f"unknown widget_type {widget_type!r}",
                "input": widget_type,
            }
        ]
    )


@router.post(
    "/{dashboard_id}/widgets", response_model=DashboardRead, status_code=201,
    description=_WIDGET_DOC,
)
async def create_widget(
    dashboard_id: uuid.UUID,
    body: Annotated[dict[str, Any], Body(...)],
    session: Session,
    user: CurrentUser,
) -> DashboardRead:
    return await widgets.create_widget(
        session, dashboard_id, _parse_widget_body(body), actor=user
    )


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
