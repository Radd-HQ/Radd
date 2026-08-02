# Spec 10 — SLQ (Radd Query language) + views v2: query text, swimlanes, field axes (backend)

Allowed paths: `server/src/radd/modules/items/` (new `slq/` subpackage + router `q` param),
`server/src/radd/modules/views/`, `server/migrations/versions/` (one revision on current head),
`server/tests/test_slq.py` (new — the parser/compiler is core, tests mandated),
`server/scripts/demo_views.sh` (rewrite to SLQ), `docs/modules.md`.

## The language (frozen grammar — frontend renders a cheat sheet from this)

```
query     := expr [ORDER BY order (, order)*]
expr      := term ((AND|OR) term)*        # AND binds tighter than OR
term      := [NOT] (comparison | '(' expr ')')
comparison:= field op value
           | field IN '(' value (',' value)* ')' | field NOT IN '(' … ')'
           | field IS EMPTY | field IS NOT EMPTY
op        := = | != | ~ | > | < | >= | <=
value     := bareword | 'single' | "double" quoted | number | YYYY-MM-DD | me | none
order     := field [ASC|DESC]
```
Keywords case-insensitive; field names case-sensitive as defined. `~` = case-insensitive
contains (title/text fields). `me` = current user (assignee only, v1). `none` ≡ IS EMPTY for
relation fields.

**Fields**: `project` (key), `state` (name), `category`, `kind`, `priority`, `assignee`
(email | me | none), `team` (name | none), `label` (= has label; != lacks; IN = has any),
`title` (~/=), `key` (= TD-12), `parent` (key | none), `number`, `created`, `updated`
(date comparisons) — plus **every custom field by registry key**: select/text = != IN ~,
multi_select = containment (= means contains), number/duration/date comparisons, boolean = true|false,
all support IS [NOT] EMPTY. Unknown field or type-invalid op → parse error.

**Errors**: 422 `{detail: "<human message>", position: <int>}` — position is the character
offset; messages name the token (e.g. `unknown field 'shwo' — did you mean 'show'?` — do the
one-edit-distance suggestion, it's cheap).

## Implementation

`items/slq/`: `lexer.py`, `parser.py` (AST dataclasses), `compiler.py` (AST → SQLAlchemy over
WorkItem: joins for state/assignee/team/parent, EXISTS subqueries for labels, JSONB ops for cf,
registry lookup scoped to the query's workspace for cf typing), each file small. `GET /items`
gains `q` (ANDed with any structured params, which all remain). ORDER BY applies to the SQL
(default stays created desc). RBAC filtering unchanged and applied on top. Tests: lexer/parser
round-trips, precedence, every operator per field type, error positions/suggestions, compile
smoke against a session.

## Views v2

- Columns: DROP `filters` (JSONB) + old enum `group_by`; ADD `query` TEXT NOT NULL DEFAULT '',
  `group_by` TEXT nullable, `swimlane_by` TEXT nullable. Axis token domain (validate on write):
  `state | assignee | priority | kind | team | cf.<key>` where `<key>` must be a SELECT-type
  registry field in scope; `swimlane_by` must differ from `group_by`. `view_type` list ⇒ axes null-able
  (group_by allowed for grouped lists later — accept+store, frontend may ignore).
- Migration converts existing rows: stored ViewFilters → equivalent SLQ text (resolve state ids
  → names, assignee ids → emails, team ids → names via lookups; labels/cf are already
  names/key:value; multiple values → `IN (...)`; `none` sentinel → `assignee IS EMPTY` etc.).
  Log each conversion in the migration output; on unresolvable references drop that clause, not
  the view.
- On save: parse the query (workspace-scoped registry) → 422 with position on error. `ViewRead`:
  `query`, `group_by`, `swimlane_by`, and `query_string` becomes `q=<urlencoded>` (+
  `&project_id=<id>` when project-scoped) — still appended verbatim to `GET /items?`.
- Events unchanged. demo_views.sh rewritten: SLQ round-trip exactness (incl. `IN`, `~`, cf
  multi_select containment, `assignee = none`, ORDER BY changing result order, a parse-error 422
  with position, swimlane_by validation 409/422 for same-axis or non-select cf).

Coordination: single alembic head currently `fa2747459c4b` — chain one revision, keep one head.
Frontend agent works in web/ in parallel against THIS contract. Never touch port 8000 (verify on
8001/8002, kill exact PIDs). Live data intact. pytest green overall (36 existing + new SLQ suite);
demo.sh/demo_webhooks.sh/demo_permissions.sh regression green. Commit with explicit pathspecs.
Report: grammar deviations, migration conversion log, verification output.
