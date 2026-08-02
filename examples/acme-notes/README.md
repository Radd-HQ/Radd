# acme-notes — an example external Radd plugin

A complete, independent plugin (its own `pyproject.toml` + its own UI build) that installs into a
running Radd with **zero edits to Radd**, discovered via its `radd.plugins` entry point. Copy this
directory as the starting point for a new plugin. Full reference: `docs/plugin-ui.md`.

## A plugin is two halves — know which file does what

```
src/acme_notes/
  __init__.py        ← BACKEND (Python, runs on the server)
  spec.py            ← the note entity (auto-wired table + CRUD + events + RBAC)
  ui/                ← FRONTEND (TypeScript, runs in the browser)
    src/index.tsx    ← every UI attachment (the manifest of where this plugin shows up)
    src/*.tsx        ← the components
    dist/            ← the built bundle Radd serves at /plugins/acme-notes/
```

**`__init__.py` (server)** declares only what the server needs to know:
- the **entity** (`entities=(NOTE,)`),
- the **nav LINKS** — a sidebar item and a Settings tab (`ui.nav`) — server-declared because they're
  permission-gated (`requires=…`) and appear in `/capabilities` *before* any JS loads,
- and `remote=` — the **URL of the UI bundle**. That's the only bridge to the frontend.

It does **not** (and cannot) say "put a tab next to VCS" — a tab is a React component, i.e. browser
code. That lives in the UI half.

**`ui/src/index.tsx` (browser)** is the manifest of **where this plugin attaches**. One row per
attachment in the `contributions` array — read it top to bottom to see the whole footprint:

| Row (`slot:`) | Where it appears |
|---|---|
| `routePage` (`match: "/notes"`) | the page body at `/notes` (the sidebar *link* is the nav item in `__init__.py`) |
| `settingsPage` (`match: "/settings/acme-notes"`) | the Settings → Notes page body |
| `issuePanelSection` | a card in the issue right-rail, above the fields |
| `issueRailBottom` | a card in the right-rail, below the fields |
| `issueTab` (`title: "Notes"`) | **a tab in the issue Activity bar, next to Version control** |
| `issueTitleAction` | a button in the issue header, next to Star/Watch/Flag |
| `viewHeader` | a summary in a **view's** toolbar, computed over the issues the user can see |

To attach somewhere new, add a row; to stop, delete it. The list of every available anchor (and the
host file that renders each `<Slot>`) is in `docs/plugin-ui.md`.

## What a plugin can compute / access (this example shows both)

- **Access to an issue's fields:** notes support `{{token}}` substitution (`substitute.ts`) — type
  `{{key}} · {{title}} · {{parent}}` (or `{{cf:<field>}}`) in a note and it renders resolved against
  the issue. The `item` the slot hands you is permission-scoped, so a field the user can't read
  resolves to empty — you can't leak what they can't see.
- **Access to a view's issues:** the `view.header` panel (`NotesViewPanel.tsx`) gets the view's
  loaded, permission-scoped issues and computes a summary (count · unassigned · busiest assignee).
- **A whole saved-view type + a dashboard widget type:** `view_types=(ViewTypeSpec("acme.notes",
  "Notes review"),)` adds a view type rendered by `NotesReviewView.tsx` (issue list left, notes editor
  right — pick it in the create-view Type dropdown); `widget_types=(WidgetTypeSpec("acme.recent-notes",
  "Most Recent Notes"),)` adds a dashboard widget (`RecentNotesWidget.tsx`, fed by `GET /notes/recent`).
  Both render via the plugin's `view.type` / `dashboard.widget` slots, matched by key.
- **Extending the query language (SLQ):** the plugin registers a `note` SLQ field (`slq.py` +
  `slq_fields=(SlqFieldSpec(...),)` in the manifest), so you can search issues by note body —
  `note ~ "rsync"` — anywhere SLQ runs, and combine it with builtins (`note ~ "x" AND state = todo`).
  The resolver returns a `Select` of matching work-item ids over the plugin's own table; the engine
  wraps it as `work_item.id IN (…)`. The **Notes page** has an SLQ bar (`NotesSearch.tsx`) that filters
  issues and shows their notes.
- **Server-side logic feeding a widget:** the plugin adds its OWN Python endpoint —
  `service.py` computes an aggregate over the whole `acme_notes` table with SQL (reaching its
  auto-wired model via `entities.model_for("note")` + the kernel session), `router.py` exposes it as
  a guarded `GET /notes/stats` wired with `routers=(router,)`, and the `NotesStats.tsx` widget on the
  Notes page fetches it with `api.get("/notes/stats")`. This is how a plugin does work the browser
  can't (an aggregate across issues) and shows the result. See `docs/plugin-ui.md` → "Logic & data
  access".

## Build & install

```sh
# build the UI bundle (from repo root, builds the host + every plugin ui/):
node web/scripts/build-all.mjs
# install the plugin package into Radd's environment (discovered via the entry point):
cd server && uv pip install -e ../examples/acme-notes
# then enable it in the app: Settings → Plugins → acme-notes → Enable
```

Disabling it in Settings → Plugins removes its UI live; uninstalling (`uv pip uninstall acme-notes`)
removes the plugin.
