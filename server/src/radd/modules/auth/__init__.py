from radd.kernel import RaddPlugin

from . import subscribers
from . import entityhost  # noqa: F401 — installs the kernel's EntityHost (RADD-892)
from .permissions import AUTH_CRUD_RESOURCES, AUTH_PERMISSIONS
from .roles_router import (
    permission_router,
    role_grant_router,
    role_router,
)
from .router import auth_router, service_account_router, token_router, user_router

# After the router chain on purpose: mcptools joins the loaded graph (RADD-889).
from . import mcptools

plugin = RaddPlugin(
    name="auth",
    description=(
        "Users, sessions, personal access tokens, and roles as data (builtin + custom "
        "permission sets, direct project membership). Spec 86: instance_role is the "
        "role ladder; builtin global roles are ensured on startup."
    ),
    depends_on=("events", "projects"),
    # RADD-892: forms/pages/timelogging are gone — auth no longer reaches into
    # the features it outranks for nav facts or wiki-space names; they register
    # NavFactSpec/GrantScopeSpec and auth iterates. What is left is the generic
    # access framework and the two SUBJECT modules, which stay direct calls
    # because `global_role_grants` has a `team_id` and a `group_id` COLUMN: the
    # subject set is closed by auth's own schema, so a registry would advertise
    # an extensibility no column list can honour.
    weak_depends=("access", "groups", "teams"),
    routers=(
        auth_router,
        user_router,
        token_router,
        service_account_router,
        role_router,
        role_grant_router,
        permission_router,
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
