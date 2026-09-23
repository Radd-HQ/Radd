from radd.kernel import CapabilitySpec, EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import SettingSpec

from . import groupsync, service, usersync
from .router import admin_router, router, team_sync_router
from .types import LdapEvent

plugin = RaddPlugin(
    name="ldap",
    # RADD-1168: emitted since spec 42 and never registered. Not a trigger.
    event_types=(
        EventTypeSpec(
            LdapEvent.LOGIN, "Directory sign-in", "Sign-in", trigger=False, entity_type="user"
        ),
    ),
    core=False,  # optional plugin — disableable via the plugin manager
    description="Sign-in and user sync with Active Directory or LDAP.",
    depends_on=("events", "projects", "auth", "settings", "groups", "teams"),
    # Per-plugin deps (§14): AD/LDAP bind needs ldap3. Maps to the `radd[ldap]` extra.
    # RADD-891: the connection + sync tunables (RADD-846/848: env is seed-only,
    # each key matches its `config.Settings` attribute so an existing deploy
    # keeps working) — moved off `settings.types`'s old hardcoded dict.
    settings_keys=(
        SettingSpec(
            key="ldap_url",
            section="directory.connection",
            type="string",
            scopes=("instance",),
            label="Server URL",
            description=(
                "The directory server, e.g. ldaps://ad.example.com:636. Leave empty to turn LDAP sign-in off. Changes take effect without a restart."
            ),
        ),
        SettingSpec(
            key="ldap_user_domain",
            section="directory.connection",
            type="string",
            scopes=("instance",),
            label="User domain",
            description=(
                "The UPN suffix people sign in with (user@THIS); also derives the "
                "default base DN (ad.example.com → DC=ad,DC=example,DC=com)."
            ),
        ),
        SettingSpec(
            key="ldap_bind_dn",
            section="directory.connection",
            type="string",
            scopes=("instance",),
            label="Bind account DN",
            description=(
                "The service account for directory searches and sync, e.g. "
                "CN=svc-radd,OU=Service Accounts,DC=ad,DC=example,DC=com. "
                "Interactive sign-in stays direct-bind and never uses it."
            ),
        ),
        SettingSpec(
            key="ldap_bind_password",
            section="directory.connection",
            type="string",
            scopes=("instance",),
            label="Bind account password",
            description=(
                "Stored as an instance setting readable by instance admins — the "
                "same trust level as the person who set it."
            ),
            secret=True,
        ),
        SettingSpec(
            key="ldap_admin_groups",
            section="directory.connection",
            type="string",
            scopes=("instance",),
            label="Admin groups",
            description=(
                "Comma-separated directory group CNs whose (transitive) members "
                "sign in as instance admins. Empty = the directory carries no "
                "role opinion (the spec-110 rule)."
            ),
        ),
        SettingSpec(
            key="ldap_group_sync_seconds",
            section="directory.groups",
            type="int",
            scopes=("instance",),
            label="Group sync interval (seconds)",
            description=(
                "How often mirrored groups are re-checked against the directory. This is the longest someone keeps access after being removed from a group in AD (signing in updates that person sooner). Takes effect from the next check."
            ),
        ),
        SettingSpec(
            key="ldap_user_sync_base",
            section="directory.usersync",
            type="string",
            scopes=("instance",),
            label="User search base DN",
            description=(
                "Where directory users are searched (user sync, imports, group-member "
                "resolution) — e.g. OU=Staff,DC=ad,DC=example,DC=com. Empty = the "
                "whole directory."
            ),
            config_attr="ldap_user_search_base",
        ),
        SettingSpec(
            key="ldap_user_sync_enabled",
            section="directory.usersync",
            type="bool",
            scopes=("instance",),
            label="Automatic user sync",
            description=(
                "Regularly import every directory user under the search base and keep their names up to date. Needs the bind account and background workers; when off, import people by hand or with Sync now."
            ),
        ),
        SettingSpec(
            key="ldap_user_sync_deactivate_missing",
            section="directory.usersync",
            type="bool",
            scopes=("instance",),
            label="Deactivate missing users",
            description=(
                "When a directory-provisioned user vanishes from the directory, "
                "deactivate the account (revokes sessions). Local and OIDC accounts "
                "are never touched. Off by default so a transient AD outage cannot "
                "lock people out."
            ),
        ),
        SettingSpec(
            key="ldap_exclude_disabled",
            section="directory.usersync",
            type="bool",
            scopes=("instance",),
            label="Skip disabled directory accounts",
            description=(
                "Exclude accounts disabled in the directory (the AD ACCOUNTDISABLE bit) "
                "from imports and sync. ON by default: on a real directory most entries "
                "are leavers — one live instance held roughly two disabled accounts per active "
                "one — and importing them fills Radd with dead users. Turning it "
                "OFF does NOT lose the history of people who have left: their existing "
                "issues, comments and worklogs keep their attribution either way."
            ),
        ),
        SettingSpec(
            key="ldap_group_search_base",
            section="directory.groups",
            type="string",
            scopes=("instance",),
            label="Group search base DN",
            description=(
                "Where directory groups are searched for the group browser, links, "
                "and imports — e.g. OU=Groups,DC=ad,DC=example,DC=com. Empty = the "
                "whole directory."
            ),
        ),
    ),
    routers=(router, admin_router, team_sync_router),
    on_startup=(service.warm, groupsync.start, usersync.start),
    on_shutdown=(groupsync.stop, usersync.stop),
    capabilities=(
        CapabilitySpec(
            "ldap",
            "LDAP / AD directory",
            "auth",
            # RADD-846: the resolved overlay, not raw env — a Directory-page
            # edit shows here after the next boundary refresh (warm() covers boot).
            check=lambda: {
                "enabled": service.enabled(),
                "bind_account": service.bind_account_enabled(),
            },
        ),
    ),
)
