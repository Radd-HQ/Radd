from radd.config import settings
from radd.kernel import CapabilitySpec
from radd.kernel import RaddPlugin

from . import groupsync, usersync
from .router import admin_router, router, team_sync_router

plugin = RaddPlugin(
    name="ldap",
    core=False,  # optional plugin — disableable via the plugin manager
    description="LDAP/AD directory sign-in (spec 42): direct UPN bind (no "
    "service account), nested-group admin mapping, SSO-only provisioning and "
    "role sync on every login. Spec 84 depth: team↔AD-group links reconciled "
    "on login / on demand / by the ldap.groupsync PeriodicLoop (bind-account "
    "gated), group search + import, and directory-user import endpoints. "
    "Spec 85: cascade-resolved search bases (Directory settings page), the "
    "ldap-usersync PeriodicLoop (automatic provision/update/deactivate), and "
    "the directory_sync_state status rows.",
    depends_on=("events", "projects", "auth", "settings", "groups", "teams"),
    # Per-plugin deps (§14): AD/LDAP bind needs ldap3. Maps to the `radd[ldap]` extra.
    python_deps=("ldap3",),
    routers=(router, admin_router, team_sync_router),
    on_startup=(groupsync.start, usersync.start),
    on_shutdown=(groupsync.stop, usersync.stop),
    capabilities=(
        CapabilitySpec(
            "ldap",
            "LDAP / AD directory",
            "auth",
            check=lambda: {
                "enabled": bool(settings.ldap_url and settings.ldap_user_domain),
                "bind_account": bool(
                    settings.ldap_url and settings.ldap_bind_dn and settings.ldap_bind_password
                ),
            },
        ),
    ),
)
