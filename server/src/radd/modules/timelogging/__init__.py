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
from radd.kernel import NavFactSpec, PermissionSpec, ProjectPurgeSpec
from radd.kernel import SettingSpec

from .slq import logged_by_item_ids

from . import categories
from . import service
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


from radd.kernel.registry import register_relation  # noqa: E402 - bindings require initialized registries
from radd.kernel.specs import RelationSpec  # noqa: E402 - bindings require initialized registries
from .models import Worklog  # noqa: E402 - bindings require initialized registries

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
    permissions=(
        PermissionSpec(
            "worklog.write", "project", "Log work on items and manage your own worklogs."
        ),
        PermissionSpec(
            "worklog.delete",
            "project",
            "Delete other people's worklogs.",
            implied_by=("project.manage",),
        ),
        PermissionSpec("timesheet.view", "global", "See other people's timesheets (global)."),
    ),
    relations=(WORKLOG_OWN,),
    # RADD-892: auth used to import this module to answer "offer the Timesheet?".
    nav_facts=(NavFactSpec(key="timesheet", resolve=service.nav_timesheet_visible),),
    # `project_timelogging` already cascades in the database; declared anyway so
    # the purge does not silently depend on a migration nobody re-reads.
    project_purges=(
        ProjectPurgeSpec(name="timelogging", tables=("project_timelogging",), order=20),
    ),
    # RADD-891: the scalar cascade keys timelogging/the timesheet read
    # (`settings.service.resolve`) — moved out of `settings.types`'s old
    # hardcoded `SETTINGS_REGISTRY` dict onto the module that owns them.
    settings_keys=(
        SettingSpec(
            key="work_week_days",
            type="string",
            scopes=("instance", "project"),
            label="Working week",
            description=(
                "Comma-separated working days (mon,tue,wed,thu,fri). Business-day SLAs "
                "resolve this per item project; the instance sets the default, projects "
                "override."
            ),
            section="timelogging",
        ),
        SettingSpec(
            key="timelog_hours_per_day",
            type="int",
            scopes=("instance",),  # global — no per-project override (spec 67 follow-up)
            label="Hours per working day",
            description=(
                "How many hours a '1d' duration means when logging time or setting "
                "estimates. Global — one instance-wide value, so durations mean the "
                "same thing on every timesheet and cycle handle."
            ),
            section="timelogging",
        ),
        SettingSpec(
            key="timesheet_day_min_hours",
            type="int",
            scopes=("instance",),
            label="Timesheet: minimum hours per workday",
            description=(
                "A working day (per the working week) with less than this logged is "
                "flagged as under-logged on the timesheet's per-person view. Leave and "
                "holiday days are never flagged."
            ),
            section="timelogging",
        ),
        SettingSpec(
            key="timesheet_day_max_hours",
            type="int",
            scopes=("instance",),
            label="Timesheet: maximum hours per day",
            description=(
                "Any day with more than this logged is flagged as over-logged on the "
                "timesheet's per-person view."
            ),
            section="timelogging",
        ),
    ),
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
        # Spec 123: configuration writes are audited with a diff; not triggers.
        EventTypeSpec(
            WorklogEvent.CATEGORY_CREATED, "Work category created", "Admin",
            trigger=False, entity_type="work_category",
        ),
        EventTypeSpec(
            WorklogEvent.CATEGORY_UPDATED, "Work category updated", "Admin",
            has_changes=True, trigger=False, entity_type="work_category",
        ),
        EventTypeSpec(
            WorklogEvent.PROJECT_TIMELOGGING_CHANGED, "Project time logging changed", "Admin",
            has_changes=True, trigger=False, entity_type="project", subjects=("project",),
        ),
    ),
)
