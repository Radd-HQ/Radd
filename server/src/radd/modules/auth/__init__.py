from radd.kernel import EventTypeSpec, RaddPlugin, SettingSpec

from . import subscribers
from . import entityhost  # noqa: F401 — installs the kernel's EntityHost (RADD-892)
from .permissions import AUTH_CRUD_RESOURCES, AUTH_PERMISSIONS
from .types import AuthEvent
from .roles_router import (
    permission_router,
    role_grant_router,
    role_router,
)
from .router import auth_router, service_account_router, token_router, user_router
from .mfa_router import mfa_admin_router, mfa_enrollment_router
from . import mfa_policy

# After the router chain on purpose: mcptools joins the loaded graph (RADD-889).
from . import mcptools

plugin = RaddPlugin(
    name="auth",
    description=(
        "People, sign-in sessions, API tokens and roles."
    ),
    depends_on=("events", "projects"),
    # Spec 123: the project's public/contributions switches, with old → new.
    event_types=(
        EventTypeSpec(
            AuthEvent.PROJECT_PUBLIC_ACCESS_CHANGED, "Project public access changed", "Admin",
            has_changes=True, trigger=False, entity_type="project", subjects=("project",),
        ),
        # RADD-1168: emitted since spec 84/86 and never registered — no label
        # in the audit catalog, and outside the has_changes contract. Not
        # triggers (the automation catalog is a parity oracle).
        EventTypeSpec(AuthEvent.USER_CREATED, "User created", "People", entity_type="user"),
        EventTypeSpec(
            AuthEvent.USER_UPDATED, "User updated", "People",
            has_changes=True, entity_type="user",
        ),
        EventTypeSpec(AuthEvent.USER_DELETED, "User deleted", "People", trigger=False, entity_type="user"),
        EventTypeSpec(AuthEvent.ROLE_CREATED, "Role created", "Admin", trigger=False, entity_type="role"),
        EventTypeSpec(
            AuthEvent.ROLE_UPDATED, "Role updated", "Admin",
            has_changes=True, trigger=False, entity_type="role",
        ),
        EventTypeSpec(AuthEvent.ROLE_DELETED, "Role deleted", "Admin", trigger=False, entity_type="role"),
        EventTypeSpec(
            AuthEvent.VIEW_AS_STARTED, "Impersonation started", "Sign-in",
            trigger=False, entity_type="user",
        ),
        EventTypeSpec(
            AuthEvent.VIEW_AS_ENDED, "Impersonation ended", "Sign-in",
            trigger=False, entity_type="user",
        ),
        # RADD-1279: an admin removed someone's two-factor enrolment.
        EventTypeSpec(
            AuthEvent.MFA_RESET, "Two-factor reset", "Sign-in",
            trigger=False, entity_type="user",
        ),
    ),
    # RADD-1279: the instance MFA policy. Enforced in `create_session`; the
    # guard refuses turning it on for an admin who is not enrolled themselves.
    settings_keys=(
        SettingSpec(
            key="require_mfa",
            section="signin.mfa",
            type="bool",
            scopes=("instance",),
            label="Require two-factor authentication",
            description=(
                "People who sign in with a Radd password must use an authenticator app. "
                "Anyone not yet set up is taken through setup at their next sign-in, "
                "before they get in; people already signed in are asked at their next "
                "sign-in. Accounts that sign in through Active Directory, Google, GitHub "
                "or another SSO provider are NOT covered: require two-factor at that "
                "identity provider instead."
            ),
            guard=mfa_policy.guard_require_mfa,
        ),
    ),
    # RADD-892: forms/pages/timelogging are gone — auth no longer reaches into
    # the features it outranks for nav facts or wiki-space names; they register
    # NavFactSpec/GrantScopeSpec and auth iterates. What is left is the generic
    # access framework and the two SUBJECT modules, which stay direct calls
    # because `global_role_grants` has a `team_id` and a `group_id` COLUMN: the
    # subject set is closed by auth's own schema, so a registry would advertise
    # an extensibility no column list can honour.
    # `settings` (RADD-1279): mfa_policy reads `require_mfa` through a deferred
    # import — settings itself depends_on auth.
    weak_depends=("access", "groups", "teams", "settings"),
    routers=(
        auth_router,
        user_router,
        token_router,
        service_account_router,
        role_router,
        role_grant_router,
        permission_router,
        mfa_enrollment_router,
        mfa_admin_router,
        ),
    # RADD-889: the directory/service-account tools of the spec-114 MCP catalog
    # live with their owner.
    mcp_tools=mcptools.MCP_TOOLS,
    # RADD-890: auth's OWN atoms — the two umbrellas plus users/roles/members/
    # service accounts. Every other module's atoms are declared by that module.
    permissions=AUTH_PERMISSIONS,
    crud_resources=AUTH_CRUD_RESOURCES,
    on_startup=(subscribers.ensure_seeded,),
)
