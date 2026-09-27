from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import EntityLinkSpec
from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec, NavFactSpec, PermissionSpec, ProjectPurgeSpec, TaskSpec
from radd.config import settings

from . import portal
from . import staging  # registers the staging attachment parent (RADD-800)
from .portal_router import requests_router as portal_requests_router, router as portal_router
from .router import router
from . import subscribers  # noqa: F401 — RADD-1174: the project-teardown hooks
from .types import FormEvent
from .validation import FormValidationError


async def _form_validation_handler(request: Request, exc: FormValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": "form submission validation failed", "errors": exc.errors},
    )


plugin = RaddPlugin(
    name="forms",
    entity_links=(
        EntityLinkSpec('form', ('/p/{project.key}/settings/forms',)),
    ),
    permissions=(
        PermissionSpec(
            "form.manage", "project", "Create and manage the project's intake forms."
        ),
    ),
    crud_resources=(CrudResourceSpec("form", "project", "intake forms", "form.manage"),),
    # RADD-892: the portal nav fact, and forms dying with their project (no FK cascade).
    nav_facts=(NavFactSpec(key="portal", resolve=portal.nav_portal_visible),),
    project_purges=(ProjectPurgeSpec(name="forms", tables=("forms",), order=20),),
    # RADD-1426: abandoned submission attachments are reclaimed (rows AND bytes).
    tasks=(
        TaskSpec(
            name="forms.staging-sweep",
            run=staging.run_sweep,
            interval=lambda: settings.form_staging_sweep_interval_seconds,
        ),
    ),
    description=(
        "Intake forms that create issues from a structured request."
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
        EventTypeSpec(
            FormEvent.SUBMITTED, "Intake form submitted", "Intake",
            item_scoped=True, subjects=("item", "project", "user"),
            payload_schema={
                "type": "object",
                "properties": {
                    "form": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
                    },
                    "channel": {"type": "string", "description": "form | portal"},
                },
            },
        ),
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
