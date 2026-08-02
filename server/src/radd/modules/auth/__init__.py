from radd.kernel import RaddPlugin

from . import subscribers
from .roles_router import (
    permission_router,
    project_member_router,
    role_grant_router,
    role_router,
)
from .router import auth_router, token_router, user_router

plugin = RaddPlugin(
    name="auth",
    description=(
        "Users, sessions, personal access tokens, and roles as data (builtin + custom "
        "permission sets, direct project membership). Spec 86: instance_role is the "
        "role ladder; builtin global roles are ensured on startup."
    ),
    depends_on=("events", "projects"),
    routers=(
        auth_router,
        user_router,
        token_router,
        role_router,
        role_grant_router,
        permission_router,
        project_member_router,
    ),
    on_startup=(subscribers.ensure_seeded,),
)
