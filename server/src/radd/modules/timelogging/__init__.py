"""Time logging + timesheets (spec 22).

Per-project-optional plugin: an item can carry an original estimate and worklog
entries (duration, day, optional work category, note); a global timesheet
aggregates logged time for the day/week/month reports, filterable by team or person.
Estimates + worklogs live in this module's own tables, so the items module never
depends on time logging.
"""

from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin, SlqFieldSpec

from .slq import logged_by_item_ids

from . import categories
from .category_router import router as category_router
from .duration import DurationError
from .enablement_router import router as enablement_router
from .timesheet_router import router as timesheet_router
from .types import WorklogEvent
from .worklog_router import router as worklog_router

# After the router chain on purpose: mcptools joins the loaded graph (RADD-889).
from . import mcptools


async def _duration_error_handler(request: Request, exc: DurationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


from radd.kernel.registry import register_relation
from radd.kernel.specs import RelationSpec
from .models import Worklog

# RADD-816 (Q4): what @own MEANS for a worklog — the author column. Both forms
# mandatory (the RADD-823 contract); registered on the manifest so the loader's
# clear() cannot drop it.
WORKLOG_OWN = RelationSpec(
    resource="worklog",
    key="own",
    label="they authored",
    where=lambda actor: Worklog.author_id == actor.user_id,
    holds=lambda actor, row: row.author_id == actor.user_id,
)
register_relation(WORKLOG_OWN)

plugin = RaddPlugin(
    name="timelogging",
    relations=(WORKLOG_OWN,),
    description=(
        "Per-project time logging: worklogs (duration/day/work-category/note) + item "
        "estimates, and a global timesheet for day/week/month reports filterable by "
        "team or person. Estimates/worklogs are module-owned so items stays independent. "
        "Default work categories seed on startup (ensure_seeded)."
    ),
    depends_on=("events", "projects", "auth", "teams", "items", "settings"),
    # `logged_by = me` on the ITEM dialect — see slq.py. Registered here rather
    # than hardcoded in items, so items keeps no knowledge of worklogs.
    slq_fields=(
        SlqFieldSpec(name="logged_by", label="Logged by", item_ids=logged_by_item_ids),
    ),
    routers=(worklog_router, category_router, enablement_router, timesheet_router),
    # RADD-889: the worklog tools of the spec-114 MCP catalog live with their owner.
    mcp_tools=mcptools.MCP_TOOLS,
    exception_handlers=((DurationError, _duration_error_handler),),
    on_startup=(categories.ensure_seeded,),
    event_types=(
        EventTypeSpec(WorklogEvent.CREATED, "Work logged", "Time logging", item_scoped=True),
        EventTypeSpec(WorklogEvent.UPDATED, "Worklog edited", "Time logging", item_scoped=True),
        EventTypeSpec(WorklogEvent.DELETED, "Worklog deleted", "Time logging", item_scoped=True),
    ),
)
