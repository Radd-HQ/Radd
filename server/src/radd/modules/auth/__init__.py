from radd.kernel import RaddPlugin

from . import subscribers
from .roles_router import (
    permission_router,
    project_member_router,
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
    weak_depends=("access", "forms", "groups", "pages", "teams", "timelogging"),
    routers=(
        auth_router,
        user_router,
        token_router,
        service_account_router,
        role_router,
        role_grant_router,
        permission_router,
        project_member_router,
    ),
    # RADD-889: the directory/service-account tools of the spec-114 MCP catalog
    # live with their owner.
    mcp_tools=mcptools.MCP_TOOLS,
    on_startup=(subscribers.ensure_seeded,),
)
