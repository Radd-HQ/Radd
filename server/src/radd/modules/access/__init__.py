"""Generic access-grant framework (spec 92).

A single scoped-grant primitive — subject(user|team|role) → access on a resource,
scoped global/project — that every RBAC-controlled resource (custom fields,
builtin fields, views, and plugins) shares, via `registry.register_resource`.
"""

from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="access",
    description="Generic, scopeable, plugin-registerable access grants — the one ACL "
    "primitive fields/views/plugins share.",
    depends_on=("projects", "events", "auth", "teams"),
    routers=(router,),
)
