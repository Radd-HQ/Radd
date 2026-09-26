from radd.kernel import EntityLinkSpec
from radd.kernel import CapabilitySpec, EventTypeSpec, PluginUiManifest, RaddPlugin

from . import registry, service
from .types import SsoEvent
from .admin_router import router as admin_router
from .router import router


async def _startup() -> None:
    await registry.seed_from_env()


plugin = RaddPlugin(
    name="sso",
    entity_links=(
        EntityLinkSpec('sso_provider', ('/settings/sign-in',)),
    ),
    core=False,  # optional plugin — disableable via the plugin manager
    description="Single sign-on with Google, GitHub or any OpenID Connect provider.",
    depends_on=("events", "projects", "auth", "teams"),
    routers=(router, admin_router),
    # RADD-1380: the provider registry is this plugin's own remote, contributed
    # as a SECTION of the host's Settings → Sign-in page — no nav entry, because
    # the page also carries the core auth module's MFA policy and must outlive
    # a disabled sso. The login page's buttons stay in the host: they render
    # before sign-in, when no remote can load.
    ui=PluginUiManifest(remote="/plugins/sso/remoteEntry.js", ui_api_version="1.14.0"),
    on_startup=(_startup,),
    # Spec 123: provider administration is audited with a diff; not a trigger.
    event_types=(
        # RADD-1168: emitted since spec 40 and never registered. Not triggers.
        EventTypeSpec(SsoEvent.LOGIN, "Single sign-on", "Sign-in", trigger=False, entity_type="user"),
        EventTypeSpec(
            SsoEvent.IDENTITY_LINKED, "Identity linked", "Sign-in", trigger=False, entity_type="user"
        ),
        EventTypeSpec(
            SsoEvent.PROVIDER_CREATED, "Sign-in provider created", "Admin",
            trigger=False, entity_type="sso_provider",
        ),
        EventTypeSpec(
            SsoEvent.PROVIDER_UPDATED, "Sign-in provider updated", "Admin",
            has_changes=True, trigger=False, entity_type="sso_provider",
        ),
        EventTypeSpec(
            SsoEvent.PROVIDER_DELETED, "Sign-in provider deleted", "Admin",
            trigger=False, entity_type="sso_provider",
        ),
    ),
    capabilities=(
        CapabilitySpec(
            "sso",
            "Single sign-on",
            "auth",
            # Reads the process-local snapshot (refreshed on write + at startup)
            # because a CapabilitySpec check is SYNC and cannot open a session.
            check=lambda: {
                "enabled": service.enabled(),
                "providers": len(registry.snapshot()),
            },
        ),
    ),
)
