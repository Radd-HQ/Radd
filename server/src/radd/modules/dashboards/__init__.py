from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import EventTypeSpec, RaddPlugin
from radd.kernel import CrudResourceSpec

from .router import router
from .types import DashboardEvent
from .widgets import WidgetConfigError


async def _config_handler(request: Request, exc: WidgetConfigError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


from .service import _DASHBOARD_SPEC  # noqa: E402 - bindings require initialized registries

plugin = RaddPlugin(
    name="dashboards",
    # RADD-1168: emitted since spec 57 and never registered. Not triggers.
    event_types=(
        EventTypeSpec(DashboardEvent.CREATED, "Dashboard created", "Views", trigger=False),
        EventTypeSpec(
            DashboardEvent.UPDATED, "Dashboard updated", "Views", has_changes=True, trigger=False
        ),
        EventTypeSpec(DashboardEvent.DELETED, "Dashboard deleted", "Views", trigger=False),
    ),
    # Spec 75/87: create ONLY. dashboard.create is the broadcast gate on
    # `global_access`; editing and deleting are owner/editor decisions (the spec-57
    # ownership model dashboards shipped with), so no atom was ever consulted.
    crud_resources=(
        CrudResourceSpec(
            "dashboard", "global", "dashboards", "global.manage", actions=("create", "update", "delete")
        ),
    ),
    # RADD-818: spec-92 resources ride the MANIFEST — the loader's clear()
    # wipes import-time registration, and the manifest is what survives it.
    access_resources=(_DASHBOARD_SPEC,),
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "Dashboards: widgets that chart and list your issues."
    ),
    depends_on=("events", "projects", "auth", "teams", "items", "cycles", "views", "reporting", "access", "groups"),
    routers=(router,),
    exception_handlers=((WidgetConfigError, _config_handler),),
)
