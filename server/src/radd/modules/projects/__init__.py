from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from .router import instance_router, project_router
from .types import ProjectEvent

plugin = RaddPlugin(
    name="projects",
    description="Projects: global containers, keys, per-project item numbering.",
    depends_on=("events",),
    routers=(project_router, instance_router),
    event_types=(
        EventTypeSpec(ProjectEvent.PROJECT_CREATED, "Project created", "Admin"),
    ),
)
