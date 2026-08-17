# Spec 13 — frontend: SLQ autocomplete dropdown (Jira-style)

Allowed paths: `web/` + frontend row in `docs/modules.md`. Contract: spec 12's suggest endpoint
(read it; verify shapes against live /openapi.json).

## Deliverable

A shared autocomplete layer for BOTH SLQ surfaces (the view editor textarea and the ad-hoc list
query bar — they share the editor component; extend it, don't fork):

- On typing (debounce ~150ms) and on Ctrl+Space, call
  `GET /items/slq/suggest?q=<full text>&cursor=<caret>&workspace_id=…[&project_id=…]`.
- Dropdown below the input: suggestion rows show `label` + muted `detail` (e.g. state, user
  email, field type); keyboard navigation (↑/↓, Enter/Tab accepts, Esc closes), mouse click
  accepts; accepted suggestion splices `insert` over `[replace_from, caret)` and re-triggers
  suggest at the new caret. Non-insertable hints (`insert === ""`, e.g. the date-format hint)
  render as a muted single line, not selectable.
- Show a subtle context tag in the dropdown header ("fields", "operators", "values for state").
- Empty suggestions + context value → show nothing (no empty dropdown).
- Keep the existing debounced validation (positioned errors + match count) working alongside;
  suggest calls must not race validation display (cancel stale requests).

Quality bar: this is a keyboard-first feature — verify the full keyboard path with Playwright:
type `sta` → accept `state` → operators appear → accept `=` → state values appear (scoped to the
project!) → accept a quoted multi-word state → type ` AND lab` → accept → build a full valid
query entirely via autocomplete, watch match count go live, save the view, then DELETE it (SPEC13
prefix on anything you create). Also verify Ctrl+Space reopen and Esc. Screenshots.

Environment: npm PATH bootstrap the session scratchpad;
Playwright at scratchpad/pw-browsers; backend live on :8000 (seeded admin <local dev credentials>, real data); if the suggest endpoint 404s, the backend agent hasn't landed — poll
/openapi.json for `/items/slq/suggest`, meanwhile build + verify with Playwright route mocks.
Never touch port 8000's process; vite 5173 killed by exact PID; final `npm run build` refreshes
the :8000 bundle. Commit `-- web docs/modules.md` only. `npm run build` zero TS errors.
Report: components, keyboard-path evidence, gaps.
