# Plugin UI — extension points & how to write a plugin

Current package/deployment workflow: [plugin development](plugin-development.md). Backend enable/disable changes apply after restarting all web and worker processes.
**The point:** you add UI *anywhere* in Radd by **registering a slot contribution** from your plugin,
never by editing the host or another plugin. The host renders named `<Slot>` anchors and knows no
plugin; your plugin targets an anchor by id. Adding a settings page, a new dashboard type, a tab next
to VCS, a button by the issue title, or a section under the fields is a few lines in *your* code with
zero blast radius on anyone else's.

This is the frontend companion to `docs/plugin-platform.md` (§8/§9/§14) and spec 94. It is the map:
**every place a plugin can attach, and the one recipe to attach there.**

---

## Two mechanisms

1. **Slots** — fine-grained UI injection points. The primary tool. A base view renders
   `<Slot id="…" …props />`; a plugin calls `registerSlot(id, contribution)`. The registry
   (`@radd/plugin-sdk`) is a federation singleton, so a plugin's registration lands in the same store
   the host reads, and disabling the plugin removes its contributions live.
2. **Remotes** — a plugin's UI is its own bundle in its own directory (`<plugin>/ui/`), built to
   `<plugin>/ui/dist/remoteEntry.js`, loaded at runtime. This is what gives isolation: updating one
   plugin's UI can't break another — different bundle, loaded independently. See "New plugin" below.

A plugin does not need to own a whole page to add UI — it injects into named spots. Own a whole page
only when you actually want one (`route.page`/`settings.page`).

---

## The slot vocabulary (the entry points)

All ids are members of `SlotId` in `@radd/plugin-sdk`. `props` are what the host passes to `render`.
"Grep the host" column = where the `<Slot>` lives, so you can find/add anchors.

| Slot id (`SlotId.…`) | Where it renders | props | Notes | Host anchor |
|---|---|---|---|---|
| `issueTitleAction` | Issue header, by Star/Watch/Flag | `{item, project}` | buttons/links by the title | `routes/item-detail.tsx` |
| `issuePanelSection` | Issue right-rail, above the fields | `{item, project}` | cards; `order` sorts them | `components/items/IssueProperties.tsx` |
| `issueRailBottom` | Issue right-rail, below the fields | `{item, project}` | your own section under Fields | `IssueProperties.tsx` |
| `issueTab` | Activity tab bar, next to VCS | `{item, project}` | needs `title` (+ optional `icon`); `render` = tab body | `components/items/ActivityPanel.tsx` |
| `viewHeader` | A view's header/toolbar | `{view, items}` | `items` = the view's loaded, permission-scoped issues | `routes/view.tsx` |
| `viewType` | A whole saved-view TYPE | `{view, items}` | `match` = the view_type key; pair with a `view_types=` manifest entry | `routes/view.tsx` |
| `routePage` | A full page at a nav path | `{path}` | `match` = the pathname | `components/shell/PluginPage.tsx` (splat route) |
| `settingsPage` | A full page under Settings → … | `{path}` | `match` = the pathname | `components/shell/SettingsPluginPage.tsx` |
| `settingsSection` | Into an *existing* settings page | `{}` | `match` = the page's key | *add a `<Slot>` to that page* |
| `profileSection` | The user's Profile page | `{}` | per-user prefs; drop `<UserContributionToggles>` here | `routes/settings/profile.tsx` |
| `pluginManagerSection` | A plugin's row in Settings → Plugins (admin) | `{plugin, pluginId}` | `match` = the plugin's registry name; drop `<GlobalContributionToggles>` here | `routes/settings/plugins.tsx` |
| `sidebarNav` | Left sidebar nav | `{}` | today driven by the backend nav manifest | `components/shell/Sidebar.tsx` |
| `dashboardWidget` | A dashboard widget type | `{config, widget, filterQuery}` | `match` = the widget-type key; pair with a `widget_types=` manifest entry; `filterQuery` = the dashboard-wide SLQ filter (plugin widgets decide how to honor it) | `components/dashboards/WidgetCard.tsx` |
| `itemAction` | An item's action menu | `{item}` | | *menu host* |

A contribution is `{ id, render, order?, match?, title?, icon?, label?, toggleable? }`. `id` is
unique within your plugin (dedupes re-registration); `order` sorts section/tab slots; `match` keys
page/type slots; `title`/`icon` label tab/menu slots; `label` names it in the toggle UIs;
`toggleable: false` keeps a contribution out of those lists (use it for your own control surfaces).
Every contribution renders inside an error boundary — a throw hides *your* section, never the host
view.

**To open a NEW extension point:** add an id to `SlotId` (SDK) and drop a `<Slot id=… …props/>` where
you want it in the host. That's the whole cost of making a spot pluggable.

**Per-contribution enable/disable (two scopes, plugin-owned, opt-in).** Give each contribution a
stable `id` + a human `label`. A contribution renders only when it's enabled in BOTH scopes; the
SDK filters it out of its `<Slot>` immediately when either turns it off. The kernel forces nothing —
a plugin exposes toggles by mounting the SDK widgets it wants:

- **Instance-wide (admin).** Mount `<GlobalContributionToggles plugin="my-name" pluginId={pluginId}/>`
  in a `pluginManagerSection` slot (`match` = your registry name; the host passes `pluginId`). It
  appears under your plugin's row in **Settings → Plugins**. Off here ⇒ the piece is hidden for
  **everyone** and won't be offered for per-user override. Persists to
  `/plugins/{id}/contribution-settings` (in the plugin's own `InstalledPlugin.config`).
- **Per-user.** Mount `<UserContributionToggles plugin="my-name" />` in a `profileSection` slot. Each
  user turns the *instance-enabled* pieces on/off for their own account. Persists to
  `/auth/me/preferences`, so it follows the user across browsers.

Both render an **On/Off switch** per contribution. Mark the toggle-widget contributions themselves
`toggleable: false` so they don't list — or hide — themselves. A plugin that mounts neither widget
simply has no toggle UI (Settings → Plugins shows just its Enable/Disable).

Turning off a contribution also removes it from the host surfaces that enumerate options from the
BACKEND manifest — otherwise those are blind to the toggle. The SDK exposes the turned-off keys:
`useDisabledNavPaths()` (route/settings pages) and the general `useDisabledMatches(slot)` (any keyed
slot). With them the host filters out a turned-off entry everywhere it could otherwise leak:

- **Nav links** — both the main sidebar and the Settings sidebar drop the link for a disabled
  `routePage`/`settingsPage`; a direct visit shows a "this page has been turned off" notice instead
  of an endless spinner.
- **The Type dropdowns** — a disabled `viewType`/`dashboardWidget` stops being offered when
  creating/editing a view or dashboard widget, and an EXISTING view/widget of a turned-off type
  shows the notice (`MissingPluginType disabled`) rather than a blank surface.

**Missing types degrade gracefully.** If a saved view or dashboard widget references a plugin
view/widget type whose plugin is now disabled/uninstalled, the host shows a clear "type no longer
available — check with your instance admin" message instead of a broken or empty render
(`MissingPluginType`).

---

## Logic & data access — where computation goes and what a plugin can see

**Where does a plugin's logic/calculations live?**
- **Client-side (most cases):** in the plugin's UI components (`ui/src/*.tsx`). It runs over the data
  the host hands the slot (props) plus anything it fetches via the SDK (`api`, `useItemQuery`,
  `useItemsQuery`, `useProjectsQuery`, `usePermissions`). Substituting `{{title}}` in a note, or
  summarizing a view's issues, is client-side.
- **Server-side (heavy / authoritative / DB-backed):** the plugin's Python package adds its own
  endpoints (`routers=(router,)` in the manifest) + a `service.py`, and the UI calls them with
  `api.get("/my-endpoint")`. Those run on the server with the acting user's permissions (§7.5), so a
  heavy computation, a cross-issue aggregate, or something that must not be trusted to the client goes
  here. (The auto-wired entity CRUD at `/api/v1/<plural>` is the zero-code version of this.)

**What context does a plugin get, and can it see everything?** Each slot hands `render` the relevant,
**already permission-scoped** context via props:
- an **issue** slot (`issue.*`) gets `{ item, project }` — `item` is the host's *hydrated* object, so
  it contains exactly the fields the current user may read (field-level grants applied, spec 92). A
  plugin can read `item.title`, `item.state`, `item.custom_fields`, `item.parent`, … but a field the
  user can't see simply isn't there — so a plugin **cannot leak what the user can't see**.
- a **view** slot (`view.header`) gets `{ view, items }` — `items` is the view's currently-loaded,
  permission-scoped issues (the same list the user is looking at). Compute over exactly that.
- a **page** slot (`route.page`/`settings.page`) gets `{ path }` and fetches its own data via the SDK
  hooks, which are permission-scoped by the backend.

Need more than props give you? Fetch through the SDK (`api` / the `use*Query` hooks) — every one is
scoped to the acting user by the server, so the "can't see more than the user" guarantee holds whether
data arrives by props or by fetch.

**Extending the query language (SLQ).** Slots aren't the only extension point — the backend has the
same `register_*` registries. A plugin can add a **searchable SLQ field** by declaring
`slq_fields=(SlqFieldSpec(name="note", label=…, item_ids=resolver),)` in its manifest; the resolver
returns a SQLAlchemy `Select` of matching work-item ids (over the plugin's OWN table), and the items
query engine wraps it as `work_item.id IN (…)`. Then `note ~ "text"` works everywhere SLQ runs —
saved views, the query bar, `useItemsQuery` — and composes with builtins (`note ~ "x" AND state =
todo`). Supported operators: `=`, `!=`, `~` (contains). The example registers `note` in `slq.py`.

Likewise a plugin adds a whole **saved-view type** (`view_types=(ViewTypeSpec(key, label),)`) or a
**dashboard widget type** (`widget_types=(WidgetTypeSpec(key, label),)`). The backend accepts the new
type on view/widget create + lists it in `/capabilities`; the frontend Type dropdowns show it, and the
plugin renders it via the `view.type` / `dashboard.widget` slot (matched by the key). The example ships
a "Notes review" view type (`NotesReviewView.tsx`: issue list + notes editor) and a "Most Recent Notes"
widget (`RecentNotesWidget.tsx`, fed by its own `GET /notes/recent`). All of it — SLQ field, view type,
widget type, endpoints, UI — is torn down together when the plugin is disabled. The example plugin demonstrates all of this: `{{token}}`
substitution reads the issue's fields (`substitute.ts`), and the `view.header` panel
(`NotesViewPanel.tsx`) computes a summary over the view's visible issues.

## Writing a plugin (the recipe)

Copy `examples/acme-notes/` — a complete, independent plugin that attaches to six anchors. It is the
template. A plugin is:

```
<plugin>/                      # a Python package (builtin: server/src/radd/modules/<n>/; external: its own repo)
  __init__.py                  # plugin = RaddPlugin(id, name, version, entities=…, ui=PluginUiManifest(…))
  spec.py                      # (optional) EntitySpec → auto-wired table + CRUD + events + RBAC
  ui/                          # the UI, colocated with the plugin
    package.json               # depends on @radd/plugin-sdk
    vite.config.mjs            # `export default raddRemote(dirname(...))` — config from the SDK
    tsconfig.json
    src/index.tsx              # export default definePlugin({ activate(ctx){ ctx.registerSlot(...) } })
    src/<components>.tsx        # your UI — imports ONLY @radd/plugin-sdk (+ react/react-query)
    dist/remoteEntry.js         # built output, served at /plugins/<name>/ from HERE
```

Backend manifest (`__init__.py`):

```python
from radd.sdk import NavItemSpec, PluginUiManifest, RaddPlugin
plugin = RaddPlugin(
    id="acme.notes", name="acme-notes", version="1.0.0", core=False,
    entities=(NOTE,),                        # optional: a table + CRUD + events + RBAC, auto-wired
    ui=PluginUiManifest(
        nav=(NavItemSpec(key="acme-notes", label="Notes", path="/notes", section="main",
                         requires=("item.read",)),),        # section="settings" ⇒ a Settings tab
        remote="/plugins/acme-notes/remoteEntry.js",        # the UI bundle URL
        ui_api_version="1.0.0",                              # host version-gates this
    ),
)
```

UI entry (`ui/src/index.tsx`) — **declarative style (preferred): every attachment is one row, so the
whole footprint is visible at a glance.** The render is a React component (browser code), which is why
UI attachments live here, not in the Python manifest.

```tsx
import { definePlugin, SlotId, Button } from "@radd/plugin-sdk";
export default definePlugin({
  contributions: [
    { slot: SlotId.issueTitleAction, render: () => <Button small>Note</Button> },      // button by the title
    { slot: SlotId.issueTab, title: "Notes", render: ({ item }) => <MyTab item={item}/> }, // tab next to VCS
    { slot: SlotId.routePage, match: "/notes", render: () => <MyPage/> },                // the /notes page body
    // …add a row to attach anywhere; delete it to stop.
  ],
});
```

Prefer this to the imperative escape hatch (`activate(ctx) { ctx.registerSlot(…) }`), which exists for
dynamic/conditional registration. `id` is optional (defaults to `<slot>#<index>`).

Rules that keep it isolated:
- Import UI only from `@radd/plugin-sdk` (slots, `Button/TextField/Select/Card/Chip/Avatar/tokens/…`,
  hooks `useCurrentUser/usePermissions/useItemQuery/…`, the `api` client). Never import `web/src` or
  another plugin.
- Style with `tokens.*` / SDK primitives — no hardcoded hex; you inherit the host theme (light/dark).
- Data comes from the auto-wired CRUD API (`/api/v1/<plural>`) or `api.*`; the SDK hooks are
  permission-scoped.

Build: `node web/scripts/build-all.mjs` discovers every `<plugin>/ui/` and builds it. Install an
external plugin with `uv pip install -e <path>` (it's discovered via its `radd.plugins` entry point),
then enable it in **Settings → Plugins** — its UI loads at runtime, and restart the web and workers to apply the requested state.

---

## Boundaries & follow-ups

- **Core frame stays host-owned.** The app shell, projects, board/list, the issue-view *frame*,
  workflow, and custom fields are the always-on tracker; they are slot *hosts*, not remotes.
  Federating them would add runtime-load machinery for UI that's never disabled — cost, no benefit.
  Everything *optional/feature* (dashboards, docs, cycles, forms, connectors, settings panels) is a
  plugin remote.
- **`dashboardWidget` / `viewType` need a backend type-registry** to be fully pluggable end-to-end
  (today `widget_type`/`view_type` are validated against a backend enum). The frontend slot is the
  UI half; making the *type* pluginnable is the same inversion already done for permissions and event
  types (`register_*`) — a bounded backend follow-up.
- **`settingsSection`** is available; wire it by dropping `<Slot id={SlotId.settingsSection}
  match="<pageKey>"/>` into whichever settings page should accept injected sections.
