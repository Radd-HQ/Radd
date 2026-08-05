from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import PermissionSpec, ProjectPurgeSpec
from radd.kernel import SettingSpec

from .enums import ItemEvent
from .filters import FilterParseError
from .router import router
from .service.visibility import ITEM_RELATIONS
from .slq import SlqError

# Imported AFTER the router chain: mcptools reaches sideways (service, workflow,
# comments-deferred), so it must join an already-loaded graph rather than be the
# first entry into it — an early import here is a collection-time cycle (RADD-889).
from .mcptools import MCP_TOOLS


async def _filter_parse_handler(request: Request, exc: FilterParseError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


async def _slq_handler(request: Request, exc: SlqError) -> JSONResponse:
    # Spec 10 error contract: the message + the character offset of the bad token.
    return JSONResponse(
        status_code=422, content={"detail": str(exc), "position": exc.position}
    )


plugin = RaddPlugin(
    name="items",
    # RADD-890: the work-item atoms are declared where they are enforced.
    permissions=(
        PermissionSpec("item.read", "project", "See the project's work items."),
        PermissionSpec("item.create", "project", "Create work items in the project."),
        PermissionSpec(
            "item.update",
            "project",
            "Edit the project's work items.",
            # RADD-790: anyone who may edit an issue may attach to it. That is what
            # makes splitting attachments off `item.update` a WIDENING and never a
            # downgrade — every existing role keeps exactly what it had, with no
            # data migration, and a role created tomorrow inherits the same rule.
            # RADD-816: `attachment.delete` means ANYONE's now, so what item.update
            # carries is the @own form — a qualified atom, which is why this is
            # `implies` and not the attachment side's `implied_by`.
            implies=("attachment.create", "attachment.delete@own"),
        ),
        PermissionSpec(
            "item.delete", "project", "Hard-delete work items.", implied_by=("project.manage",)
        ),
    ),
    description=(
        "Work items: CRUD, per-project keys (TD-42), epic/issue/subtask hierarchy, "
        "assignee + team, custom fields inline everywhere, SLQ text queries (`q`)."
    ),
    # RADD-891: the story-points opt-in (spec 70) — moved off `settings.types`'s
    # old hardcoded dict. Resolved directly by the SPA via
    # `GET /scoped-settings/resolve` (`usePointsEnabled`), not by server code —
    # items is still the true owner: `models.py`'s estimate_points column is
    # what it gates.
    settings_keys=(
        SettingSpec(
            key="estimation_points",
            type="bool",
            scopes=("instance", "project"),
            label="Story points",
            description=(
                "Estimate items in story points (0–999, one decimal) alongside time "
                "tracking (spec 70). Off by default — a project that hasn't opted in "
                "shows no points UI; velocity/burnup can then report in points."
            ),
        ),
    ),
    depends_on=("projects", "workflow", "labels", "fields", "cycles", "releases", "auth", "teams", "events", "access", "itemtypes", "linktypes"),
    weak_depends=("approvals", "comments", "timelogging"),
    routers=(router,),
    exception_handlers=(
        (FilterParseError, _filter_parse_handler),
        (SlqError, _slq_handler),
    ),
    event_types=(
        EventTypeSpec(ItemEvent.CREATED, "Item created", "Items", item_scoped=True),
        EventTypeSpec(ItemEvent.UPDATED, "Item updated", "Items", item_scoped=True, has_changes=True),
        EventTypeSpec(ItemEvent.DELETED, "Item deleted", "Items"),
    ),
    # RADD-823: what @own / @team MEAN for an item (D6 reporter; D13 item.team_id).
    relations=ITEM_RELATIONS,
    # RADD-892: `work_items.project_id` carries no ON DELETE CASCADE, so a dying
    # project takes its items with it explicitly. Ordered after the tables that
    # point AT an item (order 20) and before the states/types it points at.
    project_purges=(ProjectPurgeSpec(name="items", tables=("work_items",), order=50),),
    # RADD-889: the item tools of the spec-45/114 MCP catalog live with their owner.
    mcp_tools=MCP_TOOLS,
)
