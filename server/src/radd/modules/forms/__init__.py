from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from .portal_router import router as portal_router
from .public_router import router as public_router
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
    description=(
        "Template-scoped intake forms (spec 17): capture structured intake against the "
        "field registry and create a work item with defaults applied. Spec 62 adds the "
        "tokened public (no-login) render/submit path under /public/forms/{token}. "
        "Spec 73 adds portal sharing (form_shares grant rows, PUT /forms/{id}/sharing) "
        "and the authenticated requester-portal directory under /portal/forms."
    ),
    depends_on=(
        "projects", "auth", "teams", "fields", "workflow", "labels", "cycles", "releases",
        "items", "events",
    ),
    routers=(router, public_router, portal_router),
    exception_handlers=((FormValidationError, _form_validation_handler),),
    event_types=(
        EventTypeSpec(FormEvent.CREATED, "Intake form created", "Admin"),
        EventTypeSpec(FormEvent.UPDATED, "Intake form updated", "Admin"),
    ),
)
