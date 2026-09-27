"""Widget CRUD + per-type config validation (spec 75). Shape is pydantic (422; a
PATCH's config revalidates against the STORED type); then SLQ must compile (422)
and referenced projects/cycles/views must be readable by the WRITER (409).
Render-time visibility stays with each widget's own endpoint ("Unavailable").
"""

import uuid
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import changes, registries
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
    ReportTimeInStateConfig,
    SlqCountConfig,
    SlqListConfig,
    ViewCountConfig,
    WidgetCreate,
    WidgetLayoutSave,
    WidgetUpdate,
)
from .types import BUILTIN_WIDGET_TYPES, DashboardEntity, DashboardEvent, WidgetType


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
        case SlqCountConfig() | SlqListConfig():
            if config.project_id is not None:
                await _readable_project(session, actor, config.project_id)
            if config.q.strip():
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


def _config_error(widget_type: str, exc: ValidationError) -> str:
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first["loc"]) or "config"
    return f"{widget_type} config: {where}: {first['msg']}"


def plugin_config(widget_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """A contributed type's config as stored: shape-checked against the spec's
    `config_model` when the plugin names one (RADD-1462; a misfit is the same 422 a
    builtin gets), else verbatim. A type whose plugin is off right now has no spec
    and keeps what it had — the row outlives the plugin (see personal.save)."""
    spec = registries.widget_types.get(widget_type)
    model = spec.config_model if spec is not None else None
    if model is None:
        return dict(config)
    try:
        return model.model_validate(config).model_dump(mode="json")
    except ValidationError as exc:
        raise WidgetConfigError(_config_error(widget_type, exc)) from None


def _write_widget(widget: DashboardWidget, data: WidgetCreate | PluginWidget, position: int) -> None:
    """Write a validated create body onto a row. A plugin-contributed type's config
    is the plugin's (`plugin_config`); the column is a String, so the key persists."""
    plugin = isinstance(data, PluginWidget)
    widget.widget_type = data.widget_type if plugin else WidgetType(data.widget_type).value
    widget.title = data.title
    widget.width = data.width
    widget.height = data.height
    widget.collapsed = data.collapsed
    widget.position = position
    widget.config = (
        plugin_config(data.widget_type, data.config) if plugin else data.config.model_dump(mode="json")
    )


async def create_widget(
    session: AsyncSession,
    dashboard_id: uuid.UUID,
    data: WidgetCreate | PluginWidget,
    actor: User,
) -> DashboardRead:
    dashboard = await service.require_edit(session, dashboard_id, actor)
    if not isinstance(data, PluginWidget):
        await _check_references(session, actor, dashboard, data.config)
    widget = DashboardWidget(dashboard_id=dashboard.id)
    _write_widget(widget, data, data.position)
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
    if data.height is not None:
        widget.height = data.height
    if data.collapsed is not None:
        widget.collapsed = data.collapsed
    if data.position is not None:
        widget.position = data.position
    if data.config is not None and widget.widget_type in BUILTIN_WIDGET_TYPES:
        model = WIDGET_CONFIG_MODELS[WidgetType(widget.widget_type)]
        try:
            config = model.model_validate(data.config)
        except ValidationError as exc:
            raise WidgetConfigError(_config_error(widget.widget_type, exc)) from None
        await _check_references(session, actor, dashboard, config)
        widget.config = config.model_dump(mode="json")
    elif data.config is not None:
        widget.config = plugin_config(widget.widget_type, data.config)
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


async def replace_widgets(
    session: AsyncSession, dashboard_id: uuid.UUID, data: WidgetLayoutSave, parse, actor: User
) -> DashboardRead:
    """Replace the whole layout, refusing a stale `expected` (409). `parse` is the
    router's body dispatcher, run only once the edit gate and the staleness check pass."""
    dashboard = await service.require_edit(session, dashboard_id, actor)
    current = await service.get_dashboard_read(session, dashboard_id, actor=actor)
    if [w.model_dump(mode="json") for w in current.widgets] != [
        w.model_dump(mode="json") for w in data.expected
    ]:
        raise ConflictError(
            "dashboard", reason="Dashboard changed elsewhere. Reload before editing."
        )
    parsed = [parse(raw) for raw in data.widgets]
    stored = {
        str(row.id): row
        for row in await session.scalars(
            select(DashboardWidget).where(DashboardWidget.dashboard_id == dashboard_id)
        )
    }
    kept = set()
    for index, (raw, row) in enumerate(zip(data.widgets, parsed)):
        widget_id = raw.get("id")
        if widget_id in kept:
            raise ConflictError("dashboard", reason="Duplicate widget id")
        kept.add(widget_id)
        if not isinstance(row, PluginWidget):
            await _check_references(session, actor, dashboard, row.config)
        model = stored.get(widget_id)
        if model is None:
            model = DashboardWidget(dashboard_id=dashboard_id)
            session.add(model)
        _write_widget(model, row, index)
    for widget_id, model in stored.items():
        if widget_id not in kept:
            await session.delete(model)
    await session.flush()
    await service.emit(
        session,
        DashboardEvent.UPDATED,
        dashboard,
        actor,
        diff=[{"field": "widgets", "from": "Previous layout", "to": "Updated layout"}],
    )
    return await service.get_dashboard_read(session, dashboard_id, actor=actor)
