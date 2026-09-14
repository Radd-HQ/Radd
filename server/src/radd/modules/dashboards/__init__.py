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
            "dashboard", "global", "dashboards", "global.manage", actions=("create",)
        ),
    ),
    # RADD-818: spec-92 resources ride the MANIFEST — the loader's clear()
    # wipes import-time registration, and the manifest is what survives it.
    access_resources=(_DASHBOARD_SPEC,),
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "Composable dashboards (spec 75): user-assembled widget grids over data "
        "surfaces that ALREADY exist — the /reports/* endpoints, SLQ counts/lists "
        "(GET /items/count, GET /items?q=), and POST /views/counts. The module "
        "owns layout + ownership/sharing (the spec-57 view idiom verbatim: "
        "owner + viewer|editor|owner grants + global_access, non-visible → "
        "404); every widget FETCHES through the existing read APIs at render "
        "time, so RBAC/visibility filtering is inherited, not reimplemented."
    ),
    depends_on=("events", "projects", "auth", "teams", "items", "cycles", "views", "reporting", "access", "groups"),
    routers=(router,),
    exception_handlers=((WidgetConfigError, _config_handler),),
)
