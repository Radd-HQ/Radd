from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from .enums import ItemEvent
from .filters import FilterParseError
from .router import router
from .service.visibility import ITEM_RELATIONS
from .slq import SlqError


async def _filter_parse_handler(request: Request, exc: FilterParseError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


async def _slq_handler(request: Request, exc: SlqError) -> JSONResponse:
    # Spec 10 error contract: the message + the character offset of the bad token.
    return JSONResponse(
        status_code=422, content={"detail": str(exc), "position": exc.position}
    )


plugin = RaddPlugin(
    name="items",
    description=(
        "Work items: CRUD, per-project keys (TD-42), epic/issue/subtask hierarchy, "
        "assignee + team, custom fields inline everywhere, SLQ text queries (`q`)."
    ),
    depends_on=(
        "projects", "workflow", "labels", "fields", "cycles", "releases", "auth", "teams", "events"
    ),
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
)
