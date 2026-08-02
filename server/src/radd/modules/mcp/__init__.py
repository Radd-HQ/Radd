from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="mcp",
    core=False,  # optional plugin — disableable via the plugin manager
    description="Embedded MCP server (spec 45): hand-rolled Streamable-HTTP JSON-RPC at "
    "POST {api_prefix}/mcp — PAT-authed agents drive the same RBAC'd service layer as "
    "humans. Doc tools appear automatically when the docs module is live.",
    depends_on=("auth", "projects", "workflow", "fields", "items", "comments"),
    routers=(router,),
)
