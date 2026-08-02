# Spec 12 — SLQ autocomplete: server-driven suggest endpoint (backend)

Allowed paths: `server/src/radd/modules/items/` (slq/ additions + router), `server/tests/test_slq_suggest.py`
(new — grammar-adjacent core, tests mandated), `server/scripts/demo_views.sh` (append a suggest scene),
`docs/modules.md`. No migration needed.

## Endpoint (contract FROZEN — frontend builds against it)

`GET /api/v1/items/slq/suggest?q=<text>&cursor=<int>&workspace_id=<uuid>[&project_id=<uuid>]`
(auth required; project_id → require item.read on it; else any member of workspace_id; cursor
defaults to len(q)).

Response:
```json
{
  "context": "field" | "operator" | "value" | "keyword",
  "replace_from": 17,          // offset where the token being completed starts (== cursor if fresh)
  "field": "state" | null,     // set when context is operator/value: the field in play
  "suggestions": [
    {"value": "In Progress", "insert": "\"In Progress\"", "label": "In Progress", "detail": "state"}
  ]
}
```
`insert` is spliced verbatim over [replace_from, cursor) — it carries quoting when the value
needs it (spaces/keywords). Max 20 suggestions, case-insensitive prefix matches ranked before
contains matches, then alphabetical.

## Context detection

Reuse the existing lexer on q[:cursor] (don't reimplement grammar): classify from the trailing
complete tokens —
- start / after AND, OR, NOT, `(` → context=field: all builtin fields + every registry cf key
  in scope (detail = field name/type), plus keyword NOT.
- after a field → context=operator: exactly that field type's valid ops from the existing
  catalog op-tables (incl. IN, NOT IN, IS EMPTY, IS NOT EMPTY as multi-word inserts).
- after an operator, `IN (`, or a comma inside IN → context=value (see sources below).
- after a complete comparison / `)` → context=keyword: AND, OR, ORDER BY.
- after ORDER BY / a comma in the order list → context=field (sortable ones only); after an
  order field → ASC, DESC.
- mid-token (cursor inside a partial word) → same context as above with replace_from at the
  token start and the partial as the filter prefix; inside a quoted string → value context with
  the open quote respected (insert closes the quote).

## Value sources (scope = project if given, else workspace)

state → distinct state names in scope; category/kind/priority → enum values; assignee →
`me`, `none`, then active users (insert email, label display name, detail email);
team → `none` + team names; label → label names; project → project keys; parent/key → item keys
matching the prefix (ILIKE on project key + number, limit applies; parent also offers `none`);
cf select/multi_select → registry options; boolean cf → true/false; date fields (created/updated
+ date cf) → one template suggestion `{"value":"YYYY-MM-DD","insert":"","label":"YYYY-MM-DD",
"detail":"date format hint"}` (insert empty = non-insertable hint); text/number/url/duration →
empty suggestions (context still reported).

Note in modules.md: value suggestions expose workspace entity names (states/labels/users/teams)
to any workspace member — consistent with open-visibility defaults; revisit with guest roles.

## Verify

pytest suite: context detection at every position class (incl. mid-token, inside quotes, inside
IN lists, after ORDER BY), op-tables per field type, ranking, quoting of spacey values, scope
narrowing (project states only), limit. demo_views.sh scene: 3 real curl suggest calls (field
ctx, state values with "In Progress" quoted insert, cf.show options) asserting content. Full
regression: pytest + demo.sh/demo_webhooks.sh/demo_permissions.sh/demo_views.sh green on 8001/8002
(NEVER port 8000; kill exact PIDs). Single alembic head unchanged. Commit with explicit pathspecs.
Report: contract deviations, verification output, gaps.
