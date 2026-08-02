from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

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


plugin = RaddPlugin(
    name="fields",
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
