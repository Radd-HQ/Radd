from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="mcp",
    core=False,  # optional plugin — disableable via the plugin manager
    description="An MCP server so AI agents can work with Radd using a person's or service account's permissions.",
    depends_on=("auth", "projects", "fields", "linktypes"),
    weak_depends=("pages",),
    routers=(router,),
)
