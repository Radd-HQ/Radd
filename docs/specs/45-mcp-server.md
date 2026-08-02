# Spec 45 — Embedded MCP server at /mcp

Agents as first-class principals: an **MCP (Model Context Protocol) server
embedded in the tracker app**, so any MCP client (Claude Code, Claude
Desktop, custom agents) can drive Radd through the SAME RBAC'd service layer
as humans — authenticated as a (service-account) user via PAT.

## Design

New module `radd.modules.mcp` — **NO tables**. Rather than pull in an MCP
framework, the module implements the protocol's HTTP transport directly
(Streamable HTTP: JSON-RPC 2.0 over POST): tiny, dependency-free, and
testable. `POST /mcp` (also mounted under the api prefix) handles:

- `initialize` → protocol version + capabilities `{tools: {}}` + server info.
- `notifications/initialized` → 202.
- `tools/list` → the tool catalog (below), with JSON-Schema inputs.
- `tools/call` → dispatch, results as `{content: [{type: "text", text:
  <JSON>}]}`; domain errors return `isError: true` with the message.

**Auth**: `Authorization: Bearer radd_pat_…` resolved through the existing
PAT machinery → a real `User`; every tool call goes through the ordinary
service/authz seams — an agent can do exactly what its principal may do,
nothing more. Unauthenticated → 401. `RADD_MCP_ENABLED` (default true).

## Tools (v1 catalog — generated, not hand-frozen)

- `search_items(slq, workspace?, limit=25)` — run an SLQ query (the full
  language, autocomplete grammar documented in the tool description).
- `get_item(key)` — full item incl. custom fields inline + comments tail.
- `create_item(project_key, title, kind?, description?, state?, priority?,
  assignee_email?, labels?, custom_fields?)`.
- `update_item(key, …same optional fields…, state?)`.
- `comment_item(key, body, internal?=false)`.
- `list_projects(workspace?)` / `list_workspaces()`.
- `get_doc_page(id)` / `search_docs(query)` when the docs module is enabled
  (feature-detect via the module registry, i.e. settings.modules).

The `custom_fields` parameter's schema is built LIVE from the field
registry (`fields.service` definitions — same source as OpenAPI), so
studio-defined fields appear as documented properties automatically.

## Tests

Pure/protocol: initialize/tools-list/tools-call envelope handling, unknown
method → JSON-RPC error, tool schema generation from a stubbed registry.
End-to-end: ASGI client with a real PAT — search + create + comment round
trip (integration step).

## Known simplifications

- Streamable HTTP POST only (no SSE streaming responses, no sessions beyond
  auth, no resources/prompts capabilities) — tools are the point; the rest
  can layer in.
- Tool catalog v1 covers the tracker + docs read; automations/reports/etc.
  ride the REST API via `search_items`-adjacent additions later.
