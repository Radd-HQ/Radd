from radd.kernel import CapabilitySpec, EventTypeSpec, RaddPlugin

from . import registry, service
from .types import SsoEvent
from .admin_router import router as admin_router
from .router import router


async def _startup() -> None:
    await registry.seed_from_env()


plugin = RaddPlugin(
    name="sso",
    core=False,  # optional plugin — disableable via the plugin manager
    description="Single sign-on (spec 40 → 110): a registry of OIDC providers "
    "(Google preset + generic issuers), code+PKCE flows, per-provider signup "
    "domain allowlists, and federated identities linked to existing accounts.",
    depends_on=("events", "projects", "auth", "teams"),
    routers=(router, admin_router),
    on_startup=(_startup,),
    # Spec 123: provider administration is audited with a diff; not a trigger.
    event_types=(
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
