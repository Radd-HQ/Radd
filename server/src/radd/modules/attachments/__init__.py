from radd.kernel import CapabilitySpec, EventTypeSpec, IntegrationSpec
from radd.kernel.sockets import Socket
from radd.kernel import RaddPlugin
from radd.kernel import PermissionSpec

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


async def _shutdown() -> None:
    """Nothing to stop: orphan cleanup is a registered cascade now (RADD-745),
    drained by the kernel's single consumer rather than a loop per module."""


from radd.kernel.registry import register_relation  # noqa: E402 - bindings require initialized registries
from radd.kernel.specs import RelationSpec  # noqa: E402 - bindings require initialized registries
from .models import Attachment  # noqa: E402 - bindings require initialized registries

# RADD-816 (Q4): what @own MEANS for a attachment — the author column. Both forms
# mandatory (the RADD-823 contract); registered on the manifest so the loader's
# clear() cannot drop it.
ATTACHMENT_OWN = RelationSpec(
    resource="attachment",
    key="own",
    label="they authored",
    where=lambda actor: Attachment.created_by == actor.user_id,
    holds=lambda actor, row: row.created_by == actor.user_id,
)
register_relation(ATTACHMENT_OWN)

from .acl import _SPEC as _ATTACHMENT_SPEC  # noqa: E402 - bindings require initialized registries

plugin = RaddPlugin(
    cascades=lambda: gc.cascades(),
    name="attachments",
    # RADD-790: attaching a file is its OWN authority. It used to be `item.update`,
    # which conflated "may edit this issue" with "may add a file to it" — a role
    # built to discuss an issue without editing it commented fine and 403'd the
    # moment the editor pasted a screenshot, so it read as "commenting is broken".
    permissions=(
        PermissionSpec(
            "attachment.create",
            "project",
            "Attach files to items and comments.",
            implied_by=("project.manage",),
        ),
        PermissionSpec(
            "attachment.delete",
            "project",
            "Delete anyone's attachments.",
            implied_by=("project.manage",),
        ),
    ),
    # RADD-818: spec-92 resources ride the MANIFEST — the loader's clear()
    # wipes import-time registration, and the manifest is what survives it.
    access_resources=(_ATTACHMENT_SPEC,),
    relations=(ATTACHMENT_OWN,),
    description="File attachments on work items and wiki pages (spec 102): "
    "multiple storage hosts (filesystem/S3) as DB rows, per-host proxy or "
    "presigned delivery, routed uploads, blob API for other modules.",
    depends_on=("events", "projects", "auth", "items", "access", "groups", "teams"),
    weak_depends=("ai",),
    # Per-plugin deps (§14): the S3 backend needs the MinIO SDK. Maps to the
    # `radd[s3]` extra; the default filesystem backend needs nothing extra.
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
