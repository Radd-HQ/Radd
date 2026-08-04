"""Generic access-grant framework (spec 92).

A single scoped-grant primitive — subject(user|team|role) → access on a resource,
scoped global/project — that every RBAC-controlled resource (custom fields,
builtin fields, views, and plugins) shares, via `registry.register_resource`.
"""

from radd.kernel import RaddPlugin

from .router import router

from radd.kernel.specs import TaskSpec

from .service import sweep_expired_grants

plugin = RaddPlugin(
    name="access",
    # RADD-820: expired grants are absent at resolution; this just buries them.
    tasks=(TaskSpec(name="access.expiry-sweep", run=sweep_expired_grants, interval=3600.0),),
    description="Generic, scopeable, plugin-registerable access grants — the one ACL "
    "primitive fields/views/plugins share.",
    depends_on=("projects", "events", "auth", "teams"),
    routers=(router,),
)
