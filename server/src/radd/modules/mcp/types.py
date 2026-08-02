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

# tools/call result shaping.
GET_ITEM_COMMENTS_TAIL = 10  # most-recent comments inlined by get_item
SEARCH_LIMIT_DEFAULT = 25
SEARCH_LIMIT_MAX = 100


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
    PING = "ping"
    TOOLS_LIST = "tools/list"
    TOOLS_CALL = "tools/call"


class McpContentType(StrEnum):
    """tools/call result content block types (v1: text only)."""

    TEXT = "text"


class McpTool(StrEnum):
    """The v1 tool catalog. Doc tools appear only when the pages module is
    enabled AND exposes the service functions we need (feature-detected)."""

    SEARCH_ITEMS = "search_items"
    FIND_ITEMS = "find_items"  # text/meaning search (hybrid FTS+vector, spec 103)
    GET_ITEM = "get_item"
    CREATE_ITEM = "create_item"
    UPDATE_ITEM = "update_item"
    COMMENT_ITEM = "comment_item"
    LINK_ITEMS = "link_items"  # RADD-739
    UNLINK_ITEMS = "unlink_items"  # RADD-739
    LIST_PROJECTS = "list_projects"
    GET_PAGE = "get_page"
    SEARCH_PAGES = "search_pages"
    # --- spec 114: families that appear only for keys that may use them ---
    GET_ALLOWED_TRANSITIONS = "get_allowed_transitions"
    TRANSITION_ITEM = "transition_item"
    LOG_WORK = "log_work"
    LIST_WORKLOGS = "list_worklogs"
    LIST_RELEASES = "list_releases"
    CREATE_RELEASE = "create_release"
    SWEEP_RELEASE = "sweep_release"  # RADD-673: the spec-112 pipeline step, agent-reachable
    SET_ITEM_RELEASE = "set_item_release"
    LIST_USERS = "list_users"
    LIST_SERVICE_ACCOUNTS = "list_service_accounts"
    CREATE_SERVICE_ACCOUNT = "create_service_account"


# The doc tools ride the pages module (spec 43), which may be absent or a stub.
WORKLOG_WINDOW_DAYS = 30  # spec 114: list_worklogs default window

PAGE_TOOLS = frozenset({McpTool.GET_PAGE, McpTool.SEARCH_PAGES})
PAGES_MODULE_PATH = "radd.modules.pages"

