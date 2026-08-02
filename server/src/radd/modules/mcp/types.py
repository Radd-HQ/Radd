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
    """The v1 tool catalog. Doc tools appear only when the docs module is
    enabled AND exposes the service functions we need (feature-detected)."""

    SEARCH_ITEMS = "search_items"
    FIND_ITEMS = "find_items"  # text/meaning search (hybrid FTS+vector, spec 103)
    GET_ITEM = "get_item"
    CREATE_ITEM = "create_item"
    UPDATE_ITEM = "update_item"
    COMMENT_ITEM = "comment_item"
    LIST_PROJECTS = "list_projects"
    GET_DOC_PAGE = "get_doc_page"
    SEARCH_DOCS = "search_docs"


# The doc tools ride the docs module (spec 43), which may be absent or a stub.
DOC_TOOLS = frozenset({McpTool.GET_DOC_PAGE, McpTool.SEARCH_DOCS})
DOCS_MODULE_PATH = "radd.modules.docs"
