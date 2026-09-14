from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import EntityRefSpec, EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import PermissionSpec, ProjectPurgeSpec, ProjectRelationSpec
from radd.kernel import SettingSpec

from .enums import ItemEvent
from .filters import FilterParseError
from .router import router
from . import subscribers  # noqa: F401 — RADD-1174: the project-teardown hooks
from .service.refs import item_ref
from .enums import ItemVisibility
from .service.visibility import ITEM_RELATIONS, ITEM_ROW_GUARD
# AFTER the submodule imports above, deliberately: binding the package
# attribute earlier re-enters `items.schemas` before it is initialised.
from . import service
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
            key="item_default_visibility",
            type="string",
            scopes=("instance", "project"),
            label="Default issue visibility",
            description=(
                "What a new issue is unless the filer says otherwise (spec 121): "
                "public (readable by anyone who can read the project — the world, "
                "when the project is public), internal (members only), or "
                "restricted (only the reporter, assignee and participants). An HR "
                "project sets restricted; a public tracker keeps public."
            ),
            choices=tuple(v.value for v in ItemVisibility),
        ),
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
    depends_on=("projects", "workflow", "labels", "fields", "cycles", "releases", "auth", "teams", "events", "access", "itemtypes", "linktypes", "settings"),
    weak_depends=("approvals", "comments", "timelogging"),
    routers=(router,),
    exception_handlers=(
        (FilterParseError, _filter_parse_handler),
        (SlqError, _slq_handler),
    ),
    event_types=(
        EventTypeSpec(
            ItemEvent.CREATED, "Item created", "Items",
            item_scoped=True, subjects=("item",),
        ),
        EventTypeSpec(
            ItemEvent.UPDATED, "Item updated", "Items",
            item_scoped=True, has_changes=True, subjects=("item",),
        ),
        EventTypeSpec(ItemEvent.DELETED, "Item deleted", "Items", subjects=("item",)),
    ),
    # RADD-923: how an item describes itself inside ANY event payload. Declared
    # once here; eleven other modules name `item` as a subject and none of them
    # builds the shape — the kernel does, so it cannot come out differently.
    entity_refs=(EntityRefSpec("item", item_ref, label="Issue"),),
    # RADD-823: what @own / @team MEAN for an item (D6 reporter; D13 item.team_id).
    relations=ITEM_RELATIONS,
    row_guards=(ITEM_ROW_GUARD,),
    # RADD-892: `work_items.project_id` carries no ON DELETE CASCADE, so a dying
    # project takes its items with it explicitly. Ordered after the tables that
    # point AT an item (order 20) and before the states/types it points at.
    project_purges=(ProjectPurgeSpec(name="items", tables=("work_items",), order=50),),
    # RADD-937: an item you reported/are assigned, or that your team owns,
    # makes its project visible even with no grant on it.
    project_relations=(
        ProjectRelationSpec(
            key="item",
            label="you reported or are assigned an item here",
            resolve=service.projects_with_user_items,
        ),
        ProjectRelationSpec(
            key="team_item",
            label="one of your teams owns an item here",
            resolve=service.projects_with_team_items,
        ),
    ),
    # RADD-889: the item tools of the spec-45/114 MCP catalog live with their owner.
    mcp_tools=MCP_TOOLS,
)
