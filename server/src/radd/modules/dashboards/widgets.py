"""Widget CRUD + per-type config validation (spec 75).

Shape validation is pydantic: create bodies are a discriminated union on
`widget_type` (schemas.WidgetCreate — unknown type / wrong config shape 422 at
the boundary); a PATCH's `config` is revalidated here against the widget's
STORED type (WidgetConfigError → 422 via the module handler). SEMANTIC checks
then run per type: SLQ compiles against the scope registry (SlqError → 422
{detail, position} via the items module's app-wide handler), and referenced
projects/cycles/views must exist and be visible/readable to the WRITER → 409
(everything is global now — spec 86). Render-time visibility stays with each
widget's own endpoint — a viewer who can't read a widget's scope gets that
endpoint's 403/404 and the card renders "Unavailable".
"""

import uuid

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import changes
from radd.exceptions import ConflictError, NotFoundError, RaddError
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.cycles import service as cycles_service
from radd.modules.items import service as items_service
from radd.modules.views import service as views_service
from radd.modules.projects import service as projects_service

from . import service
from .models import Dashboard, DashboardWidget
from .schemas import (
    WIDGET_CONFIG_MODELS,
    DashboardRead,
    PluginWidget,
    ReportBurnupConfig,
    ReportProjectConfig,
    ReportSlaConfig,
    ReportTimeInStateConfig,
    SlqCountConfig,
    SlqListConfig,
    ViewCountConfig,
    WidgetCreate,
    WidgetUpdate,
)
from .types import DashboardEntity, DashboardEvent, WidgetType


class WidgetConfigError(RaddError):
    """A PATCH config that doesn't fit the widget's stored type (→ 422)."""


async def _readable_project(
    session: AsyncSession, actor: User, project_id: uuid.UUID
) -> None:
    """The referenced project must exist and be readable by the WRITER — all
    409 (a broken reference is a config conflict, not a missing route)."""
    try:
        project = await projects_service.get_project(session, project_id)
    except NotFoundError:
        raise ConflictError(
            DashboardEntity.DASHBOARD, reason=f"no such project {project_id}"
        ) from None
    perms = await authz.effective_permissions(session, actor, project=project)
    if not authz.holds_base(perms, Permission.ITEM_READ):
        raise ConflictError(
            DashboardEntity.DASHBOARD, reason=f"you cannot read project {project.key}"
        )


async def _check_references(
    session: AsyncSession, actor: User, dashboard: Dashboard, config: BaseModel
) -> None:
    """Per-type semantic validation of an already shape-valid config."""
    match config:
        case ReportProjectConfig() | ReportTimeInStateConfig():
            await _readable_project(session, actor, config.project_id)
        case ReportBurnupConfig():
            try:
                await cycles_service.get_cycle(session, config.cycle_id)
            except NotFoundError:
                raise ConflictError(
                    DashboardEntity.DASHBOARD, reason=f"no such cycle {config.cycle_id}"
                ) from None
        case ReportSlaConfig() | SlqCountConfig() | SlqListConfig():
            if config.project_id is not None:
                await _readable_project(session, actor, config.project_id)
            if isinstance(config, (SlqCountConfig, SlqListConfig)) and config.q.strip():
                # Compile against the scope registry — SlqError propagates as
                # the spec-10 422 {detail, position} (items module handler).
                await items_service.validate_slq(
                    session, actor=actor, q=config.q, project_id=config.project_id
                )
        case ViewCountConfig():
            try:
                await views_service.visible_view(session, config.view_id, actor)
            except NotFoundError:
                raise ConflictError(
                    DashboardEntity.DASHBOARD,
                    reason=f"view {config.view_id} does not exist or is not visible to you",
                ) from None


async def create_widget(
    session: AsyncSession,
    dashboard_id: uuid.UUID,
    data: WidgetCreate | PluginWidget,
    actor: User,
) -> DashboardRead:
    dashboard = await service.require_edit(session, dashboard_id, actor)
    if isinstance(data, PluginWidget):
        # Plugin-contributed type (registries.widget_types): the config is
        # free-form and owned by the plugin — stored verbatim, no builtin
        # reference checks apply. The column is a String, so the key persists.
        widget = DashboardWidget(
            dashboard_id=dashboard.id,
            widget_type=data.widget_type,
            title=data.title,
            width=data.width,
            position=data.position,
            config=dict(data.config),
        )
    else:
        await _check_references(session, actor, dashboard, data.config)
        widget = DashboardWidget(
            dashboard_id=dashboard.id,
            widget_type=WidgetType(data.widget_type).value,
            title=data.title,
            width=data.width,
            position=data.position,
            config=data.config.model_dump(mode="json"),
        )
    session.add(widget)
    await session.flush()
    await service.emit(
        session, DashboardEvent.UPDATED, dashboard, actor,
        diff=[{"field": "widgets", "added": [_label(widget)], "removed": []}],
    )
    return await service.hydrate_one(session, actor, dashboard)


def _label(widget: DashboardWidget) -> str:
    """A widget as an auditor reads it: its title, else its type."""
    return widget.title or widget.widget_type


async def _get_widget(
    session: AsyncSession, dashboard: Dashboard, widget_id: uuid.UUID
) -> DashboardWidget:
    widget = await session.get(DashboardWidget, widget_id)
    if widget is None or widget.dashboard_id != dashboard.id:
        raise NotFoundError(DashboardEntity.DASHBOARD, widget_id)
    return widget


async def update_widget(
    session: AsyncSession,
    dashboard_id: uuid.UUID,
    widget_id: uuid.UUID,
    data: WidgetUpdate,
    actor: User,
) -> DashboardRead:
    dashboard = await service.require_edit(session, dashboard_id, actor)
    widget = await _get_widget(session, dashboard, widget_id)
    before = changes.snapshot(widget, ("title", "width", "position", "config"))
    # Omitted = unchanged, explicit null clears the title override.
    if "title" in data.model_fields_set:
        widget.title = data.title
    if data.width is not None:
        widget.width = data.width
    if data.position is not None:
        widget.position = data.position
    if data.config is not None:
        model = WIDGET_CONFIG_MODELS[WidgetType(widget.widget_type)]
        try:
            config = model.model_validate(data.config)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(part) for part in first["loc"]) or "config"
            raise WidgetConfigError(
                f"{widget.widget_type} config: {where}: {first['msg']}"
            ) from None
        await _check_references(session, actor, dashboard, config)
        widget.config = config.model_dump(mode="json")
    await session.flush()
    diff = changes.diff_object(widget, before, hidden=("config",), labels={
        "title": f"{_label(widget)} title",
        "width": f"{_label(widget)} width",
        "position": f"{_label(widget)} position",
        "config": f"{_label(widget)} configuration",
    })
    await service.emit(session, DashboardEvent.UPDATED, dashboard, actor, diff=diff)
    return await service.hydrate_one(session, actor, dashboard)


async def delete_widget(
    session: AsyncSession, dashboard_id: uuid.UUID, widget_id: uuid.UUID, actor: User
) -> None:
    dashboard = await service.require_edit(session, dashboard_id, actor)
    widget = await _get_widget(session, dashboard, widget_id)
    label = _label(widget)
    await session.delete(widget)
    await session.flush()
    await service.emit(
        session, DashboardEvent.UPDATED, dashboard, actor,
        diff=[{"field": "widgets", "added": [], "removed": [label]}],
    )
