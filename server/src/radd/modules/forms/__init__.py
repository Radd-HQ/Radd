from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec, NavFactSpec, PermissionSpec, ProjectPurgeSpec

from . import portal
from . import staging  # noqa: F401 — registers the staging attachment parent (RADD-800)
from .portal_router import requests_router as portal_requests_router, router as portal_router
from .router import router
from .types import FormEvent
from .validation import FormValidationError


async def _form_validation_handler(request: Request, exc: FormValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": "form submission validation failed", "errors": exc.errors},
    )


plugin = RaddPlugin(
    name="forms",
    permissions=(
        PermissionSpec(
            "form.manage", "project", "Create and manage the project's intake forms."
        ),
    ),
    crud_resources=(CrudResourceSpec("form", "project", "intake forms", "form.manage"),),
    # RADD-892: the two facts about forms other machinery used to reach in for —
    # whether the portal is worth a nav link, and that a form dies with its
    # project (`forms.project_id` carries no ON DELETE CASCADE).
    nav_facts=(NavFactSpec(key="portal", resolve=portal.nav_portal_visible),),
    project_purges=(ProjectPurgeSpec(name="forms", tables=("forms",), order=20),),
    description=(
        "Template-scoped intake forms (spec 17): capture structured intake against the "
        "field registry and create a work item with defaults applied. Spec 62 adds the "
        "RADD-828 removed the tokened public path — email ingest provisions a requester account instead. "
        "Spec 73 adds portal sharing (form_shares grant rows, PUT /forms/{id}/sharing) "
        "and the authenticated requester-portal directory under /portal/forms."
    ),
    depends_on=("projects", "auth", "teams", "fields", "workflow", "labels", "cycles", "releases", "items", "events", "comments", "itemtypes"),
    weak_depends=("attachments", "automations"),
    routers=(router, portal_router, portal_requests_router),
    exception_handlers=((FormValidationError, _form_validation_handler),),
    event_types=(
        EventTypeSpec(FormEvent.CREATED, "Intake form created", "Admin", subjects=("project",)),
        EventTypeSpec(
            FormEvent.UPDATED, "Intake form updated", "Admin",
            has_changes=True, subjects=("project",),
        ),
        EventTypeSpec(FormEvent.DELETED, "Intake form deleted", "Admin", trigger=False),
        # `trigger=False` — housekeeping, not something anyone writes a rule on.
        # "When unclaimed attachments are reclaimed, then…" is noise in the
        # automation dropdown, and the catalog is a parity oracle (67 triggers)
        # that should only move when the AUTOMATABLE surface really changes.
        EventTypeSpec(
            FormEvent.STAGING_DELETED,
            "Unclaimed submission attachments reclaimed",
            "Admin",
            trigger=False,
        ),
    ),
)
