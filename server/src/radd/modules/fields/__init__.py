from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec, PermissionSpec

from .openapi import augment_openapi
from .router import router
from .service import warm_schema_cache
from .types import FieldEvent
from .validation import FieldValidationError


async def _validation_handler(request: Request, exc: FieldValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": "custom field validation failed", "errors": exc.errors},
    )


from .service import _BUILTIN_SPEC, _FIELD_SPEC

plugin = RaddPlugin(
    name="fields",
    permissions=(
        PermissionSpec(
            "field.manage",
            "project",
            "Manage custom-field definitions and field access rules.",
            implied_by=("project.manage",),
        ),
    ),
    crud_resources=(CrudResourceSpec("field", "project", "custom fields", "field.manage"),),
    # RADD-818: spec-92 resources ride the MANIFEST — the loader's clear()
    # wipes import-time registration, and the manifest is what survives it.
    access_resources=(_FIELD_SPEC, _BUILTIN_SPEC),
    description="Field-definition registry: the single source of truth for dynamic schema.",
    depends_on=("projects", "events", "auth", "teams", "access"),  # access: grant resource
    routers=(router,),
    exception_handlers=((FieldValidationError, _validation_handler),),
    openapi_augmentors=(augment_openapi,),
    on_startup=(warm_schema_cache,),
    event_types=(
        EventTypeSpec(FieldEvent.CREATED, "Custom field created", "Admin"),
        EventTypeSpec(FieldEvent.UPDATED, "Custom field updated", "Admin"),
    ),
)
