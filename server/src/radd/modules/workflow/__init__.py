from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec, PermissionSpec, ProjectPurgeSpec
from radd.kernel import SettingSpec

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
    # RADD-892: order 70 — every item points at a state, so items go first. The
    # transitions must go before the states they join, which the hardcoded list
    # this replaces never did: it named `states` alone, and a project with any
    # transition row could not be purged at all.
    project_purges=(
        ProjectPurgeSpec(
            name="workflow", tables=("workflow_transitions", "states"), order=70
        ),
    ),
    # RADD-891: the enforcement mode workflow.check_transition resolves per
    # item project — moved off `settings.types`'s old hardcoded dict.
    settings_keys=(
        SettingSpec(
            key="workflow_transition_mode",
            type="string",
            scopes=("instance", "project"),
            # Mirror of workflow.types.TransitionMode (settings must not import a
            # module that depends on it).
            choices=("off", "guards", "strict"),
            label="Workflow transition enforcement",
            description=(
                "Off: anyone can move items to any state — the transitions list is "
                "ignored. Guarded: a move that has a transition defined must meet its "
                "conditions and approvals; moves with no transition defined stay "
                "allowed. Strict: the list becomes the complete map — a move with no "
                "transition defined is blocked outright (and defined moves still check "
                "their conditions). Set per project, or here for every project."
            ),
            section="workflow",
        ),
    ),
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
