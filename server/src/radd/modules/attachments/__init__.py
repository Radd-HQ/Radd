from radd.kernel import EntityLinkSpec
from radd.kernel import CapabilitySpec, EventTypeSpec, IntegrationSpec
from radd.kernel.sockets import Socket
from radd.kernel import RaddPlugin
from radd.kernel import PermissionSpec

from fastapi import Request
from fastapi.responses import JSONResponse

from . import acl, clients, gc, hosts  # noqa: F401 — acl registers the ResourceSpec
from .admin_router import router as admin_router
from .router import router, too_large_handler
from . import subscribers  # noqa: F401 — RADD-1174: the project-teardown hooks
from .routing import rules as routing_rules
from .routing.store import RuleConfigError
from .service import AttachmentTooLarge
from .types import AttachmentEvent, RuleType


async def _rule_config_handler(request: Request, exc: RuleConfigError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


def _storage_capability() -> dict[str, object]:
    """Sync, off the default-host snapshot; `backend` is the host type the pill shows."""
    default = hosts.default_snapshot()
    backend, name = default.get("type", ""), default.get("name", "")
    return {
        "enabled": bool(default),
        "backend": backend,
        "default": name,
        "summary": f"{name} ({backend})" if default else "",
    }


async def _startup() -> None:
    await hosts.encrypt_plaintext_credentials()  # RADD-1446
    await hosts.seed_from_env()
    await clients.ensure_all_ready()


from radd.kernel.registry import register_relation  # noqa: E402 - bindings require initialized registries
from radd.kernel.specs import RelationSpec  # noqa: E402 - bindings require initialized registries
from .models import Attachment  # noqa: E402 - bindings require initialized registries

# `@own` on an attachment = its author (RADD-816); both forms are mandatory
# (RADD-823), and it rides the manifest so the loader's clear() cannot drop it.
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
    entity_links=(
        EntityLinkSpec('storage_host', ('/settings/storage',)),
        EntityLinkSpec('storage_rule', ('/settings/storage',)),
    ),
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
    # RADD-818: on the manifest, because the loader's clear() wipes import-time registration.
    access_resources=(_ATTACHMENT_SPEC,),
    relations=(ATTACHMENT_OWN,),
    # RADD-1304: `attachment.create@own` = on issues they reported (the file does not
    # exist yet); `attachment.delete@own` keeps the attachment's own relation.
    relation_domains=(("attachment.create", "item"),),
    description="File attachments on issues and pages, stored on the hosts you configure and routed by rules you set.",
    depends_on=("events", "projects", "auth", "items", "access", "groups", "teams"),
    routers=(router, admin_router),
    exception_handlers=(
        (AttachmentTooLarge, too_large_handler),
        (RuleConfigError, _rule_config_handler),
    ),
    on_startup=(_startup,),
    event_types=(
        EventTypeSpec(AttachmentEvent.CREATED, "Attachment added", "Attachments", item_scoped=True),
        EventTypeSpec(AttachmentEvent.DELETED, "Attachment removed", "Attachments", item_scoped=True),
        # Spec 123: storage administration is audited with a diff; not a trigger.
        *(
            EventTypeSpec(
                event_type, label, "Admin",
                has_changes=event_type.endswith(".updated"), trigger=False, entity_type=entity,
            )
            for event_type, label, entity in (
                (AttachmentEvent.HOST_CREATED, "Storage host created", "storage_host"),
                (AttachmentEvent.HOST_UPDATED, "Storage host updated", "storage_host"),
                (AttachmentEvent.HOST_DELETED, "Storage host deleted", "storage_host"),
                (AttachmentEvent.RULE_CREATED, "Storage rule created", "storage_rule"),
                (AttachmentEvent.RULE_UPDATED, "Storage rule updated", "storage_rule"),
                (AttachmentEvent.RULE_DELETED, "Storage rule deleted", "storage_rule"),
            )
        ),
    ),
    capabilities=(
        CapabilitySpec("storage", "Attachment storage", "storage", check=_storage_capability),
    ),
    # STORAGE_BACKEND: the impl is a CLIENT CLASS taking a StorageHost row.
    integrations=(
        IntegrationSpec(Socket.STORAGE_BACKEND, "filesystem", impl=clients.FilesystemClient),
        IntegrationSpec(Socket.STORAGE_BACKEND, "s3", impl=clients.S3Client),
        # Routing-rule types; `ai` registers `llm` (RADD-1387), never imported here.
        IntegrationSpec(
            Socket.STORAGE_ROUTING_RULE,
            RuleType.USER_CHOICE.value,
            impl=routing_rules.UserChoiceRule(),
        ),
        IntegrationSpec(
            Socket.STORAGE_ROUTING_RULE, RuleType.CIDR.value, impl=routing_rules.CidrRule()
        ),
    ),
)
