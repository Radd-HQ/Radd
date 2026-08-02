# Spec 66 — Desk polish: canned variables, send-email action, KB deflection

Service-desk wave, part 6 — three small closers.

## 1. Canned-response variables (canned module)

- Pure `canned/render.py`: `render_canned(body, ctx: dict[str, str]) -> str`
  substituting `{{item.key}}`, `{{item.title}}`, `{{reporter.name}}`,
  `{{reporter.email}}`, `{{assignee.name}}`, `{{me.name}}` (same `{{token}}`
  regex idiom as automations/templating; unknown tokens stay verbatim).
- `GET /canned-responses/{id}/render?item_id=` (item.read on the item's
  project; `me` = the actor) → `{body}`. The comment composer's "Insert canned
  response" uses it whenever an item context exists (falls back to the raw
  body elsewhere).

## 2. Automation action `send_email` (automations module)

- New universal `ActionType.SEND_EMAIL`, params `{to, subject, body}` —
  subject/body run through the existing spec-58b `render_template` with the
  event facts + item context. `to` is a literal address or a role:
  `reporter` / `assignee` (their user email) / `contact` (the spec-62 mail
  contact). Role recipients need a target item — unresolvable → skip-log,
  same as item actions on itemless events. Sends via `radd/smtp.py` in
  `to_thread`; no events emitted (inherently loop-safe). Catalog entry +
  rule-builder params UI (recipient select-or-input, subject, body).

## 3. KB deflection (search + docs seams)

- `GET /search/deflect?q=&project_id=` (item.read): top 5 wiki pages (docs FTS
  seam) + top 5 RESOLVED items (existing item FTS filtered to done/canceled
  categories) → `{docs: [{id, title, space_name}], items: [{key, title}]}`.
- Frontend `DeflectionPanel` (debounced 400ms, ≥3 chars): renders under the
  title input in the new-issue modal and the authenticated form-submit page —
  "Maybe this answers it" article links + "Previously resolved" issue links.
  The PUBLIC form page skips it (endpoint is authenticated; noted).

## Tests

`render_canned` pure cases; deflect endpoint smoke (resolved-only filter);
send_email recipient resolution with a mocked SMTP send.

## Known simplifications

- Deflection is FTS relevance, not semantic (pgvector remains the roadmap
  upgrade; the endpoint shape won't change).
- No open-tracking/analytics on deflection (did the requester still file?).
- Canned variables are the fixed set above — no custom-field tokens yet.

## As-built notes

- **Status: built.** No schema changes — alembic head stays `d90a8f7daa8a`.
- Canned tokens live in a `CannedToken` StrEnum (types.py); the router's ctx
  builder (`service.render_context`) resolves reporter/assignee via
  `auth.users_by_ids` and puts `""` for unset users, and the pure
  `render_canned` treats empty values like unknown tokens (verbatim) — so
  "{{assignee.name}}" survives visibly on an unassigned item.
- send_email recipient resolution sits in `automations/email_action.py`:
  `to` matching an `EmailRecipient` member (case-insensitive) is a role,
  anything else is a literal address passed through trimmed. Reporter/assignee
  require an ACTIVE account (csat-sender idiom); `contact` uses the mailintake
  seam via a deferred feature-detected import (mailintake loads after
  automations in RADD_MODULES). The smtp-unconfigured guard is a planner skip
  (`smtp_host` empty), so `/test` previews also report it as unresolvable.
- `DeflectDoc` carries `space_id` beyond the spec's `{id, title, space_name}`
  — the SPA's doc-page route is `/docs/$spaceId/$pageId`, links need it.
- The deflect endpoint only includes the docs half when the caller also holds
  `doc.read` (the permission union `authz.require` returns) — item.read alone
  must not leak wiki titles. Resolved-items are scoped to the given project
  (its states define done/canceled); docs search spans the workspace.
- The docs half of deflect is a deferred feature-detected import (docs loads
  AFTER search): docs module disabled → `docs: []`, endpoint still works.
- DeflectionPanel links open in a new tab so the half-typed form survives the
  detour; the panel renders nothing below 3 chars or with zero hits (400 ms
  debounce via the shared `useDebounced`).
- Tests live in `tests/test_desk_polish.py` (pure render/planner cases + DB
  cases in rolled-back transactions; `radd.smtp.send_message` monkeypatched);
  the spec-58b universal-set registry test gained SEND_EMAIL.
