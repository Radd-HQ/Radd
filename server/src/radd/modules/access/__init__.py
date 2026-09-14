"""Generic access-grant framework (spec 92).

A single scoped-grant primitive — subject(user|team|role) → access on a resource,
scoped global/project — that every RBAC-controlled resource (custom fields,
builtin fields, views, and plugins) shares, via `registry.register_resource`.
"""

from radd.kernel import EventTypeSpec, RaddPlugin

from .router import router
from .types import AccessEvent

from radd.kernel.specs import TaskSpec

from .service import sweep_expired_grants

plugin = RaddPlugin(
    name="access",
    # RADD-1168: emitted since spec 92 and never registered. Not triggers.
    event_types=(
        EventTypeSpec(
            AccessEvent.GRANTED, "Access granted", "Admin",
            trigger=False, entity_type="access_grant", subjects=("project",),
        ),
        EventTypeSpec(
            AccessEvent.REVOKED, "Access revoked", "Admin",
            trigger=False, entity_type="access_grant", subjects=("project",),
        ),
    ),
    # RADD-820: expired grants are absent at resolution; this just buries them.
    tasks=(TaskSpec(name="access.expiry-sweep", run=sweep_expired_grants, interval=3600.0),),
    description="Generic, scopeable, plugin-registerable access grants — the one ACL "
    "primitive fields/views/plugins share.",
    depends_on=("projects", "events", "auth", "teams", "groups"),
    routers=(router,),
)
