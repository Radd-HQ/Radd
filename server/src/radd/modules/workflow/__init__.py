from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec, PermissionSpec

from . import subscribers  # noqa: F401  — registers the project-created hook
from .guards import TransitionError
from .router import router, category_router
from .transitions_router import router as transitions_router
from .types import StateEvent, TransitionEvent


async def _transition_handler(request: Request, exc: TransitionError) -> JSONResponse:
    # Spec 61 error contract: the failure list + the edge, for toasts/tooltips.
    return JSONResponse(
        status_code=422,
        content={
            "detail": "workflow transition blocked",
            "errors": exc.errors,
            "from_state": exc.from_state,
            "to_state": exc.to_state,
        },
    )


plugin = RaddPlugin(
    name="workflow",
    permissions=(
        PermissionSpec(
            "state.manage",
            "project",
            "Manage the project's workflow states.",
            implied_by=("project.manage",),
        ),
    ),
    crud_resources=(CrudResourceSpec("state", "project", "workflow states", "state.manage"),),
    description=(
        "Per-project named states within fixed categories; seeds defaults on project "
        "creation. Optional transition graph with validation guards (spec 61)."
    ),
    depends_on=("projects", "events", "auth", "settings", "teams"),
    weak_depends=("approvals", "comments", "fields", "items", "timelogging"),
    routers=(router, category_router, transitions_router),
    exception_handlers=((TransitionError, _transition_handler),),
    event_types=(
        EventTypeSpec(StateEvent.CREATED, "Workflow state created", "Admin"),
        EventTypeSpec(StateEvent.UPDATED, "Workflow state updated", "Admin"),
        EventTypeSpec(TransitionEvent.CREATED, "Workflow transition created", "Admin"),
        EventTypeSpec(TransitionEvent.UPDATED, "Workflow transition updated", "Admin"),
        EventTypeSpec(TransitionEvent.DELETED, "Workflow transition deleted", "Admin"),
    ),
)
