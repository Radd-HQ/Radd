from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec, PermissionSpec

from . import dispatcher, scheduler
from .router import router

plugin = RaddPlugin(
    name="automations",
    permissions=(
        PermissionSpec(
            "automation.manage", "global", "Create and manage automation rules (global)."
        ),
    ),
    crud_resources=(
        CrudResourceSpec("automation", "global", "automation rules", "automation.manage"),
    ),
    description=(
        "Event-driven rules engine (spec 15): match items by SLQ on item.created/updated, "
        "apply actions through the target services as a system actor, with a loop guard. "
        "Spec 69 adds schedule-triggered rules fired by a scheduler clock."
    ),
    depends_on=("projects", "auth", "workflow", "labels", "cycles", "releases", "items", "comments", "teams", "events", "fields"),
    weak_depends=("mailintake", "notify"),
    routers=(router,),
    on_startup=(dispatcher.start, scheduler.start),
    on_shutdown=(dispatcher.stop, scheduler.stop),
)
