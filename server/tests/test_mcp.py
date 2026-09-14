"""Embedded MCP server protocol core (spec 45).

Pure tests: JSON-RPC envelope handling (parse -> -32700/-32600, result/error
shapes), method routing (initialize / ping / unknown -> -32601), tools/call
shaping (domain error -> isError:true + rollback, unknown tool -> -32602,
arguments the advertised schema rejects -> -32602 with every violation in
`data` [RADD-1106], a handler bug -> -32603 + rollback, never an HTTP 500
[RADD-905]), tool-catalog generation from a stubbed field registry, and
pages-module feature detection. HTTP-level auth gates (401/403) ride an in-process ASGI client that
never touches the DB. The full PAT round trip is an integration step, not a
unit test (repo rule: tests only where they earn their keep).
"""

import json
from dataclasses import replace

import httpx
import pytest

from radd.config import settings
from radd.exceptions import NotFoundError
from radd.kernel import registries
from radd.modules.mcp import protocol, tools
from radd.modules.mcp.protocol import JsonRpcError, JsonRpcRequest, parse_request
from radd.modules.mcp.router import handle_request
from radd.modules.mcp.types import (
    MCP_PROTOCOL_VERSION,
    PAGE_TOOLS,
    JsonRpcErrorCode,
    McpMethod,
    McpTool,
)

TRACKER_TOOLS = {
    McpTool.SEARCH_ITEMS,
    McpTool.FIND_ITEMS,  # spec 103: text/meaning search over the hybrid ranker
    McpTool.GET_ITEM,
    McpTool.CREATE_ITEM,
    McpTool.UPDATE_ITEM,
    McpTool.COMMENT_ITEM,
    McpTool.LINK_ITEMS,  # RADD-739: an agent can express its plan's ORDER
    McpTool.UNLINK_ITEMS,
    McpTool.LIST_PROJECTS,
    McpTool.UPDATE_PROJECT,  # RADD-1009: rename + describe, project.manage
    McpTool.DELETE_PROJECT,  # RADD-1174: the whole project, global project.delete
    # Spec 114 families. build_catalog still returns EVERY tool — the narrowing
    # to what a caller may run happens in requirements.visible_catalog, which
    # tests/test_mcp_catalog.py covers.
    McpTool.GET_ALLOWED_TRANSITIONS,
    McpTool.TRANSITION_ITEM,
    McpTool.LOG_WORK,
    McpTool.LIST_WORKLOGS,
    McpTool.UPDATE_WORKLOG,  # RADD-741: derived time gets corrected
    McpTool.DELETE_WORKLOG,
    McpTool.LIST_RELEASES,
    McpTool.GET_RELEASE,
    McpTool.CREATE_RELEASE,
    McpTool.UPDATE_RELEASE,
    McpTool.SWEEP_RELEASE,  # RADD-673: the spec-112 pipeline step, agent-reachable
    McpTool.SET_ITEM_RELEASE,
    McpTool.LIST_USERS,
    McpTool.LIST_SERVICE_ACCOUNTS,
    McpTool.CREATE_SERVICE_ACCOUNT,
}


def request_body(method: str, params: dict | None = None, id: int | None = 1) -> str:
    payload: dict = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        payload["params"] = params
    if id is not None:
        payload["id"] = id
    return json.dumps(payload)


def error_of(callable_):
    with pytest.raises(JsonRpcError) as info:
        callable_()
    return info.value


# --- protocol: parsing ---


def test_parse_valid_request():
    message = parse_request(request_body("tools/list", {"cursor": None}, id=7))
    assert message.method == "tools/list"
    assert message.params == {"cursor": None}
    assert message.id == 7
    assert message.is_notification is False


def test_parse_notification_has_no_id():
    message = parse_request(request_body("notifications/initialized", id=None))
    assert message.is_notification is True
    assert message.id is None


def test_parse_invalid_json_is_parse_error():
    error = error_of(lambda: parse_request(b"{nope"))
    assert error.code is JsonRpcErrorCode.PARSE_ERROR


def test_parse_batch_arrays_rejected():
    error = error_of(lambda: parse_request(b"[]"))
    assert error.code is JsonRpcErrorCode.INVALID_REQUEST


@pytest.mark.parametrize(
    "payload",
    [
        {"jsonrpc": "1.0", "method": "ping", "id": 1},  # wrong version
        {"jsonrpc": "2.0", "id": 1},  # missing method
        {"jsonrpc": "2.0", "method": "", "id": 1},  # empty method
        {"jsonrpc": "2.0", "method": "ping", "params": [1], "id": 1},  # params not object
        {"jsonrpc": "2.0", "method": "ping", "id": {"o": 1}},  # bad id type
    ],
)
def test_parse_invalid_request_shapes(payload):
    error = error_of(lambda: parse_request(json.dumps(payload)))
    assert error.code is JsonRpcErrorCode.INVALID_REQUEST


def test_parse_error_carries_request_id_when_readable():
    error = error_of(lambda: parse_request(json.dumps({"jsonrpc": "1.0", "method": "m", "id": 9})))
    assert error.id == 9


# --- protocol: envelopes ---


def test_result_and_error_envelopes():
    assert protocol.result_envelope(3, {"ok": True}) == {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {"ok": True},
    }
    envelope = protocol.error_envelope(None, JsonRpcErrorCode.METHOD_NOT_FOUND, "nope")
    assert envelope == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32601, "message": "nope"},
    }
    with_data = protocol.error_envelope(1, JsonRpcErrorCode.INVALID_PARAMS, "bad", {"k": 1})
    assert with_data["error"]["data"] == {"k": 1}


# --- method routing ---


async def test_initialize_result_shape():
    result = await handle_request(
        None, None, JsonRpcRequest(method=McpMethod.INITIALIZE, id=1)
    )
    assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
    # RADD-740: listChanged is TRUE and honest — GET /mcp is the channel. It was
    # `{}`, which told every client the tool list was fixed for the life of the
    # connection while spec 114 made the catalog a function of the caller.
    assert result["capabilities"] == {"tools": {"listChanged": True}}
    assert result["serverInfo"]["name"] == "radd"
    assert result["serverInfo"]["version"]


async def test_ping_returns_empty_result():
    assert await handle_request(None, None, JsonRpcRequest(method="ping", id=1)) == {}


async def test_unknown_method_is_method_not_found():
    with pytest.raises(JsonRpcError) as info:
        await handle_request(None, None, JsonRpcRequest(method="resources/list", id=1))
    assert info.value.code is JsonRpcErrorCode.METHOD_NOT_FOUND


async def test_tools_call_requires_name_and_object_arguments():
    for params in ({}, {"name": 4}, {"name": "get_item", "arguments": [1]}):
        with pytest.raises(JsonRpcError) as info:
            await handle_request(
                None, None, JsonRpcRequest(method=McpMethod.TOOLS_CALL, params=params, id=1)
            )
        assert info.value.code is JsonRpcErrorCode.INVALID_PARAMS


async def test_tools_call_unknown_tool_is_invalid_params():
    with pytest.raises(JsonRpcError) as info:
        await handle_request(
            None,
            None,
            JsonRpcRequest(
                method=McpMethod.TOOLS_CALL, params={"name": "explode", "arguments": {}}, id=1
            ),
        )
    assert info.value.code is JsonRpcErrorCode.INVALID_PARAMS


# --- tools/call result shaping ---


class StubSession:
    def __init__(self):
        self.rolled_back = False

    async def rollback(self):
        self.rolled_back = True


async def test_domain_error_becomes_is_error_result_and_rolls_back(monkeypatch):
    async def boom(session, actor, args):
        raise NotFoundError("item", "TD-9999")

    # RADD-889: the handlers live on kernel specs now; stub the registered one.
    monkeypatch.setitem(
        registries.mcp_tools,
        McpTool.GET_ITEM.value,
        replace(registries.mcp_tools[McpTool.GET_ITEM.value], handler=boom),
    )
    session = StubSession()
    result = await handle_request(
        session,
        None,
        JsonRpcRequest(
            method=McpMethod.TOOLS_CALL,
            params={"name": McpTool.GET_ITEM.value, "arguments": {"key": "TD-9999"}},
            id=1,
        ),
    )
    assert result["isError"] is True
    assert result["content"] == [{"type": "text", "text": "item TD-9999 not found"}]
    assert session.rolled_back is True


# --- RADD-1106/905: arguments are validated against the ADVERTISED schema ---


def _tools_call(name: str, arguments: dict) -> JsonRpcRequest:
    return JsonRpcRequest(
        method=McpMethod.TOOLS_CALL, params={"name": name, "arguments": arguments}, id=1
    )


@pytest.mark.parametrize(
    "arguments, bad_path",
    [
        ({"query": "x", "limit": "ten"}, "limit"),
        ({"query": "x", "limit": [1]}, "limit"),
    ],
)
async def test_a_mistyped_argument_is_invalid_params(arguments, bad_path):
    """`limit: "ten"` used to reach `int(raw)` inside the handler and escape as a
    ValueError-shaped tool error or a 500, depending on the tool."""
    with pytest.raises(JsonRpcError) as info:
        await handle_request(StubSession(), None, _tools_call(McpTool.SEARCH_PAGES.value, arguments))
    assert info.value.code is JsonRpcErrorCode.INVALID_PARAMS
    assert bad_path in str(info.value)
    assert [violation["path"] for violation in info.value.data] == [bad_path]
    assert set(info.value.data[0]) == {"path", "message"}


async def test_an_unknown_argument_is_invalid_params():
    """The RADD-1106 report: `list_worklogs {"key": …}` silently ignored the
    property and answered with EVERY worklog. Every tool schema is a closed
    object, and now the closure is enforced."""
    with pytest.raises(JsonRpcError) as info:
        await handle_request(
            StubSession(), None, _tools_call(McpTool.LIST_WORKLOGS.value, {"key": "TD-1"})
        )
    assert info.value.code is JsonRpcErrorCode.INVALID_PARAMS
    assert "'key'" in str(info.value)


async def test_a_handler_bug_is_internal_error_and_rolls_back(monkeypatch):
    """RADD-905: a KeyError inside a handler escaped as Starlette's HTTP 500 with
    the half-applied flush still pending."""

    async def buggy(session, actor, args):
        raise KeyError("worked_on")

    monkeypatch.setitem(
        registries.mcp_tools,
        McpTool.GET_ITEM.value,
        replace(registries.mcp_tools[McpTool.GET_ITEM.value], handler=buggy),
    )
    session = StubSession()
    with pytest.raises(JsonRpcError) as info:
        await handle_request(session, None, _tools_call(McpTool.GET_ITEM.value, {"key": "TD-1"}))
    assert info.value.code is JsonRpcErrorCode.INTERNAL_ERROR
    assert "KeyError" in str(info.value)
    assert session.rolled_back is True


async def test_tool_success_is_json_text_content(monkeypatch):
    async def ok(session, actor, args):
        return {"echo": args["key"]}

    monkeypatch.setitem(
        registries.mcp_tools,
        McpTool.GET_ITEM.value,
        replace(registries.mcp_tools[McpTool.GET_ITEM.value], handler=ok),
    )
    result = await handle_request(
        StubSession(),
        None,
        JsonRpcRequest(
            method=McpMethod.TOOLS_CALL,
            params={"name": McpTool.GET_ITEM.value, "arguments": {"key": "TD-1"}},
            id=1,
        ),
    )
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == {"echo": "TD-1"}


# --- catalog generation (stubbed registry) ---

STUB_REGISTRY = {
    "budget": {"type": "number", "title": "Budget"},
    "show": {"type": "string", "enum": ["RUX", "BNX"], "title": "Show"},
}


def test_catalog_names_and_required_fields():
    catalog = tools.build_catalog(STUB_REGISTRY, include_pages=False)
    assert {tool["name"] for tool in catalog} == {t.value for t in TRACKER_TOOLS}
    by_name = {tool["name"]: tool for tool in catalog}
    assert by_name[McpTool.SEARCH_ITEMS]["inputSchema"]["required"] == ["slq"]
    assert by_name[McpTool.CREATE_ITEM]["inputSchema"]["required"] == ["project_key", "title"]
    assert by_name[McpTool.COMMENT_ITEM]["inputSchema"]["required"] == ["key", "body"]
    for tool in catalog:  # every schema is a closed object (agents get typo safety)
        assert tool["inputSchema"]["additionalProperties"] is False


def test_catalog_custom_fields_schema_comes_from_registry():
    catalog = tools.build_catalog(STUB_REGISTRY, include_pages=False)
    by_name = {tool["name"]: tool for tool in catalog}
    for name in (McpTool.CREATE_ITEM, McpTool.UPDATE_ITEM):
        custom = by_name[name]["inputSchema"]["properties"]["custom_fields"]
        assert custom["properties"] == STUB_REGISTRY
        assert custom["additionalProperties"] is False


def test_catalog_doc_tools_appear_only_when_docs_live():
    without = {t["name"] for t in tools.build_catalog({}, include_pages=False)}
    with_docs = {t["name"] for t in tools.build_catalog({}, include_pages=True)}
    assert with_docs - without == {tool.value for tool in PAGE_TOOLS}


# --- docs feature detection ---
# RADD-889: pages_bridge (the importlib probe of the pages service) is gone.
# The doc tools are the pages plugin's OWN McpToolSpec contributions, so
# availability IS registration: absent/disabled pages plugin -> no specs in the
# kernel registry -> no doc tools, in catalog and dispatch alike.


def test_docs_unavailable_when_pages_contributes_no_tools(monkeypatch):
    for tool in PAGE_TOOLS:
        monkeypatch.delitem(registries.mcp_tools, tool.value, raising=False)
    assert tools.pages_available() is False


def test_pages_available_when_the_pages_plugin_is_registered():
    # conftest loads the full plugin set; the pages manifest carries both specs.
    assert tools.pages_available() is True


async def test_doc_handler_calls_the_pages_service(monkeypatch):
    seen = {}

    async def get_page(session, page_id):
        seen["page_id"] = page_id
        return {"title": "Farm runbook"}

    from radd.modules.pages import service as pages_service

    monkeypatch.setattr(pages_service, "get_page", get_page)
    page_id = "0d9f2c66-1cd5-4b25-9a90-1b1f4a2f3c11"
    result = await tools.call_tool(
        None, None, McpTool.GET_PAGE.value, {"id": page_id}
    )
    assert result == {"title": "Farm runbook"}
    assert str(seen["page_id"]) == page_id


# --- HTTP-level gates (no DB: anonymous requests never open a connection) ---


@pytest.fixture(scope="module")
def app():
    from radd.app import create_app

    return create_app()


async def test_unauthenticated_post_is_401(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/mcp", content=request_body("initialize"))
    assert response.status_code == 401


async def test_disabled_instance_is_403(app, monkeypatch):
    monkeypatch.setattr(settings, "mcp_enabled", False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/mcp", content=request_body("initialize"))
    assert response.status_code == 403
