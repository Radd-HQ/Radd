# Spec 02 — items expansion: hierarchy, assignment, comments (backend, Wave 2)

Allowed paths: `server/src/radd/modules/items/`, `server/src/radd/modules/comments/` (new),
`server/src/radd/config.py` (modules tuple), `server/migrations/versions/` (one new revision
on current head), `server/scripts/demo.sh` (extend), `docs/modules.md`.

Prereq: Wave 1 landed (users + teams exist). Read their service modules for helpers.

## work_items additions

- `kind` str + `ItemKind(StrEnum)`: `epic | issue | subtask`, default issue.
- `parent_id` UUID nullable FK work_items.id. Rules (enforce in service, `ConflictError` on violation):
  subtask's parent must be an issue; issue's parent (if any) must be an epic; epic has no parent.
  Parent must be in the same project. No cycles (max depth 3 makes this trivial).
- `assignee_id` UUID nullable FK users.id — validate user exists and is active.
- `team_id` UUID nullable FK teams.id — validate team belongs to the project's workspace.

## Schemas (contract FROZEN for frontend)

- `ItemCreate`/`ItemUpdate` gain: `kind` (create only), `parent_id`, `assignee_id`, `team_id`
  (all nullable; on update, explicit null clears).
- `ItemRead` gains: `kind`, `parent: {id, key, title} | null`, `assignee: {id, name} | null`,
  `team: {id, name} | null`, `child_count: int`, `comment_count: int`.
- `GET /api/v1/items` gains filters: `kind`, `assignee_id`, `team_id`, `parent_id`.
- Batch-hydrate (extend `_hydrate`): parents, assignees (`auth service users_by_ids` — add it
  there if missing, it's a one-liner allowed exception to path rules), teams (`teams_by_ids`),
  child/comment counts via grouped count queries. No N+1.

## comments module (new)

- `comments`: id, item_id FK (ondelete CASCADE), author_id FK users.id, body Text (non-empty),
  timestamps. Events: `comment.created`, `comment.updated`, `comment.deleted` (payload includes
  item_id, author_id, body excerpt ≤200 chars).
- Endpoints: `POST /api/v1/items/{item_id}/comments` {body, author_id} → CommentRead
  (id, item_id, author: {id, name}, body, created_at, updated_at); `GET /api/v1/items/{item_id}/comments`
  (ascending); `PATCH /api/v1/comments/{id}` {body}; `DELETE /api/v1/comments/{id}` → 204.
  (author_id in body is temporary until Wave 3 wires the authenticated actor — note it in modules.md.)

## Verify

Extend demo.sh: create epic → issue under it (parent), assign user + team, comment on it,
list with `?kind=epic`, show child_count/comment_count. Run full demo.sh + demo_webhooks.sh
(regressions). Show output in report.
