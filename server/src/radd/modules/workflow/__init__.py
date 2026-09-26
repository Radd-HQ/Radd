from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import (
    CrudResourceSpec, EntityLinkSpec, EventTypeSpec, PermissionSpec, ProjectPurgeSpec, RaddPlugin, SettingSpec,
)

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
    entity_links=(
        EntityLinkSpec('state', ('/p/{project.key}/settings/workflow',)),
        EntityLinkSpec('workflow_transition', ('/p/{project.key}/settings/workflow',)),
    ),
    permissions=(
        PermissionSpec(
            "state.manage",
            "project",
            "Manage the project's workflow states.",
            implied_by=("project.manage",),
        ),
    ),
    crud_resources=(CrudResourceSpec("state", "project", "workflow states", "state.manage"),),
    # order 70: items (which point at states) purge first; transitions before the states they join.
    project_purges=(
        ProjectPurgeSpec(
            name="workflow", tables=("workflow_transitions", "states"), order=70
        ),
    ),
    # Resolved per item project by transitions.check_transition.
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
            page_scopes=("project",),
        ),
    ),
    description=(
        "Workflow: each project's states and the rules for moving between them."
    ),
    depends_on=("projects", "events", "auth", "settings", "teams"),
    # approvals is not a dependency: it serves TRANSITION_CHECK.
    weak_depends=("comments", "fields", "items", "timelogging"),
    routers=(router, category_router, transitions_router),
    exception_handlers=((TransitionError, _transition_handler),),
    event_types=(
        EventTypeSpec(StateEvent.CREATED, "Workflow state created", "Admin", subjects=("project",)),
        EventTypeSpec(
            StateEvent.UPDATED, "Workflow state updated", "Admin",
            has_changes=True, subjects=("project",),
        ),
        EventTypeSpec(
            StateEvent.DELETED, "Workflow state deleted", "Admin",
            trigger=False, subjects=("project",),
        ),
        EventTypeSpec(
            StateEvent.CATEGORY_UPDATED, "State category updated", "Admin",
            has_changes=True, trigger=False, entity_type="state_category",
        ),
        EventTypeSpec(
            TransitionEvent.CREATED, "Workflow transition created", "Admin", subjects=("project",),
        ),
        EventTypeSpec(
            TransitionEvent.UPDATED, "Workflow transition updated", "Admin",
            has_changes=True, subjects=("project",),
        ),
        EventTypeSpec(
            TransitionEvent.DELETED, "Workflow transition deleted", "Admin", subjects=("project",),
        ),
    ),
)
