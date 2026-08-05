from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="mcp",
    core=False,  # optional plugin — disableable via the plugin manager
    description="Embedded MCP server (spec 45): hand-rolled Streamable-HTTP JSON-RPC at "
    "POST {api_prefix}/mcp — PAT-authed agents drive the same RBAC'd service layer as "
    "humans. Since RADD-889 every tool is a kernel McpToolSpec contributed by its owner "
    "module; this plugin is the transport, the catalog composer (spec-114 caller filter "
    "included) and the dispatcher.",
    depends_on=("auth", "projects", "fields", "linktypes"),
    routers=(router,),
)
