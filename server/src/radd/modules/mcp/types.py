"""Wire constants + enums for the embedded MCP server (spec 45).

Everything that names a protocol behavior lives here: JSON-RPC error codes,
the MCP methods this server answers, the tool names in the v1 catalog, and the
protocol revision whose semantics the supported subset implements.
"""

from enum import IntEnum, StrEnum

# The MCP revision whose semantics we implement (for the subset we support:
# initialize / notifications/initialized / ping / tools/list / tools/call).
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_SERVER_NAME = "radd"

JSONRPC_VERSION = "2.0"

# Notifications (no `id` member) are acknowledged with HTTP 202 and no body.
HTTP_ACCEPTED = 202

# tools/call result shaping (page budgets, comment tails) moved with the tools
# to their owner modules (RADD-889); the shared clamp lives in
# `radd.kernel.mcptools`.


class JsonRpcErrorCode(IntEnum):
    """JSON-RPC 2.0 protocol error codes (domain/tool failures never use these —
    they surface as `isError: true` tool results instead)."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


class McpMethod(StrEnum):
    """The supported subset of MCP methods (anything else -> METHOD_NOT_FOUND)."""

    INITIALIZE = "initialize"
    INITIALIZED = "notifications/initialized"
    TOOLS_LIST_CHANGED = "notifications/tools/list_changed"  # RADD-740 (server -> client)
    PING = "ping"
    TOOLS_LIST = "tools/list"
    TOOLS_CALL = "tools/call"


class McpContentType(StrEnum):
    """tools/call result content block types (v1: text only)."""

    TEXT = "text"


class McpTool(StrEnum):
    """The v1 tool catalog's wire NAMES. Since RADD-889 each tool is a kernel
    `McpToolSpec` contributed by its owner module; this enum stays as the
    stable name vocabulary + the catalog's builtin/plugin split (see
    catalog.CATALOG_ORDER). Doc tools ride the pages plugin's registration."""

    SEARCH_ITEMS = "search_items"
    FIND_ITEMS = "find_items"  # text/meaning search (hybrid FTS+vector, spec 103)
    GET_ITEM = "get_item"
    CREATE_ITEM = "create_item"
    UPDATE_ITEM = "update_item"
    COMMENT_ITEM = "comment_item"
    LINK_ITEMS = "link_items"  # RADD-739
    UNLINK_ITEMS = "unlink_items"  # RADD-739
    LIST_PROJECTS = "list_projects"
    UPDATE_PROJECT = "update_project"  # RADD-1009: rename + describe
    DELETE_PROJECT = "delete_project"  # RADD-1174: the whole project, permanently
    GET_PAGE = "get_page"
    SEARCH_PAGES = "search_pages"
    CREATE_PAGE = "create_page"  # RADD-1005: the wiki, writable
    UPDATE_PAGE = "update_page"
    MOVE_PAGE = "move_page"
    # --- spec 114: families that appear only for keys that may use them ---
    GET_ALLOWED_TRANSITIONS = "get_allowed_transitions"
    TRANSITION_ITEM = "transition_item"
    LOG_WORK = "log_work"
    LIST_WORKLOGS = "list_worklogs"
    UPDATE_WORKLOG = "update_worklog"  # RADD-741
    DELETE_WORKLOG = "delete_worklog"  # RADD-741
    LIST_RELEASES = "list_releases"
    GET_RELEASE = "get_release"  # RADD-908: the notes, readable
    CREATE_RELEASE = "create_release"
    UPDATE_RELEASE = "update_release"  # RADD-908: the notes, writable
    SWEEP_RELEASE = "sweep_release"  # RADD-673: the spec-112 pipeline step, agent-reachable
    SET_ITEM_RELEASE = "set_item_release"
    LIST_USERS = "list_users"
    LIST_SERVICE_ACCOUNTS = "list_service_accounts"
    CREATE_SERVICE_ACCOUNT = "create_service_account"


# The doc tools ride the pages plugin (spec 43), which may be absent or disabled.
PAGE_TOOLS = frozenset(
    {
        McpTool.GET_PAGE,
        McpTool.SEARCH_PAGES,
        McpTool.CREATE_PAGE,
        McpTool.UPDATE_PAGE,
        McpTool.MOVE_PAGE,
    }
)


#: Same headers the AI streams use: no buffering anywhere between here and the
#: client, or a notification sits in a proxy until the next byte.
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
