from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec, PermissionSpec

from . import dispatcher, scheduler
from . import subscribers  # noqa: F401 — registers the spec-119 item.creating hook
from .intake import ValidationBlocked
from .intake_router import router as intake_router
from .intake_schemas import finding_read
from .router import router


async def _validation_blocked_handler(
    request: Request, exc: ValidationBlocked
) -> JSONResponse:
    """Spec 119's error contract — the THIRD 422 vocabulary.

    `findings`, not `errors`: the field registry's `errors` name a value the API
    could not accept, and the workflow guards' name an edge it would not take.
    A finding names something a PERSON should go and fix, carries the control it
    belongs to, and is rendered against that control rather than in a list — so
    reusing the older key would have made the client guess which kind it had.
    """
    return JSONResponse(
        status_code=422,
        content={
            "detail": "item validation failed",
            "findings": [
                finding_read(finding).model_dump() for finding in exc.verdict.findings
            ],
            "mode": exc.verdict.mode.value,
        },
    )


plugin = RaddPlugin(
    name="automations",
    permissions=(
        PermissionSpec(
            "automation.manage", "global", "Create and manage automation rules (global)."
        ),
        PermissionSpec(
            "automation.act_as",
            "global",
            "Build automations whose actions run as someone else. Without it an "
            "author's automations always act as the author, and the Act as field "
            "is not offered at all — an affordance that is refused on save is "
            "worse than one that is absent.",
        ),
    ),
    crud_resources=(
        CrudResourceSpec("automation", "global", "automation rules", "automation.manage"),
    ),
    description=(
        "Event-driven rules engine (spec 15): match items by SLQ on item.created/updated, "
        "apply actions through the target services as a system actor, with a loop guard. "
        "Spec 69 adds schedule-triggered rules fired by a scheduler clock."
    ),
    depends_on=("projects", "auth", "workflow", "labels", "cycles", "releases", "items", "comments", "teams", "events", "fields", "itemtypes",),
    weak_depends=("mailintake", "notify", "leave"),
    routers=(router, intake_router),
    exception_handlers=((ValidationBlocked, _validation_blocked_handler),),
    on_startup=(dispatcher.start, scheduler.start),
    on_shutdown=(dispatcher.stop, scheduler.stop),
)
