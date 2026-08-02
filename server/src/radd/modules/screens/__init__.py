from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="screens",
    description="Field-layout (screen) config per (project, issue-type): which fields are "
    "primary / secondary-collapsed / hidden in the issue view (presentation only).",
    depends_on=("projects", "events", "auth", "fields", "itemtypes"),
    routers=(router,),
)
