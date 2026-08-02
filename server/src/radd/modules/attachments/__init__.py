from radd.kernel import CapabilitySpec, EventTypeSpec, IntegrationSpec
from radd.kernel.sockets import Socket
from radd.kernel import RaddPlugin

from fastapi import Request
from fastapi.responses import JSONResponse

from . import acl, clients, gc, hosts  # noqa: F401 — acl registers the ResourceSpec
from .admin_router import router as admin_router
from .router import router, too_large_handler
from .routing import rules as routing_rules
from .routing.store import RuleConfigError
from .service import AttachmentTooLarge
from .types import AttachmentEvent, RuleType


async def _rule_config_handler(request: Request, exc: RuleConfigError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


def _storage_capability() -> dict[str, object]:
    """Sync capability check off the default-host snapshot (refreshed at startup
    and after admin writes) — `backend` keeps its pre-102 meaning for the pill."""
    default = hosts.default_snapshot()
    return {
        "enabled": bool(default),
        "backend": default.get("type", ""),
        "default": default.get("name", ""),
    }


async def _startup() -> None:
    await hosts.seed_from_env()
    await clients.ensure_all_ready()
    await gc.start()


async def _shutdown() -> None:
    await gc.stop()


plugin = RaddPlugin(
    name="attachments",
    description="File attachments on work items and wiki pages (spec 102): "
    "multiple storage hosts (filesystem/S3) as DB rows, per-host proxy or "
    "presigned delivery, routed uploads, blob API for other modules.",
    depends_on=("events", "projects", "auth", "items"),
    # Per-plugin deps (§14): the S3 backend needs the MinIO SDK. Maps to the
    # `radd[s3]` extra; the default filesystem backend needs nothing extra.
    python_deps=("minio",),
    routers=(router, admin_router),
    exception_handlers=(
        (AttachmentTooLarge, too_large_handler),
        (RuleConfigError, _rule_config_handler),
    ),
    on_startup=(_startup,),
    on_shutdown=(_shutdown,),
    event_types=(
        EventTypeSpec(AttachmentEvent.CREATED, "Attachment added", "Attachments", item_scoped=True),
        EventTypeSpec(AttachmentEvent.DELETED, "Attachment removed", "Attachments", item_scoped=True),
    ),
    capabilities=(
        CapabilitySpec("storage", "Attachment storage", "storage", check=_storage_capability),
    ),
    # StorageBackend socket (spec 93 / A8, now in the request path — spec 102):
    # the registered impl is a CLIENT CLASS taking a StorageHost row; a plugin
    # host type is one more registration.
    integrations=(
        IntegrationSpec(Socket.STORAGE_BACKEND, "filesystem", impl=clients.FilesystemClient),
        IntegrationSpec(Socket.STORAGE_BACKEND, "s3", impl=clients.S3Client),
        # Routing-rule types (spec 102): a plugin type is one more registration.
        IntegrationSpec(
            Socket.STORAGE_ROUTING_RULE,
            RuleType.USER_CHOICE.value,
            impl=routing_rules.UserChoiceRule(),
        ),
        IntegrationSpec(
            Socket.STORAGE_ROUTING_RULE, RuleType.CIDR.value, impl=routing_rules.CidrRule()
        ),
        IntegrationSpec(
            Socket.STORAGE_ROUTING_RULE, RuleType.LLM.value, impl=routing_rules.LlmRule()
        ),
    ),
)
