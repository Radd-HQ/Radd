# Plugin UI — extension points & how to write a plugin

Current package/deployment workflow: [plugin development](plugin-development.md). Installed plugins enable and disable live. The Plugins page shows Applying until all live web/worker processes acknowledge; failures remain visible. Installing or upgrading code can still require a restart.
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
2. **Bundles** — a core plugin's UI is bundled into the host and registered at boot; an optional
   plugin's UI is its own remote (`<plugin>/ui/dist/remoteEntry.js`), loaded at runtime, so updating
   one plugin's UI cannot break another (RADD-1373). See "New plugin" below.

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
| `issueRailTop` | Issue right-rail, ABOVE the fields card (RADD-1395) | `{item, project}` | draws its own card; `order` sorts them | `routes/item-detail.tsx` |
| `itemDraftAssist` | Beside an issue being drafted — the submission form's assist panel (RADD-1395) | `ItemDraftAssistProps` `{title, description, projectId, exclude}` | render nothing when there is nothing to say: the frame is `empty:hidden`; `exclude` = keys another section shows | `components/forms/FormAssistPanel.tsx` |
| `editorToolbarAction` | A button in the rich editor's toolbar (RADD-1395) | `EditorToolbarActionProps` `{editor}` | draw it with `EditorToolbarButton`; see "The editor's extension points" | `components/editor/RichEditor.tsx` |
| `editorSelectionAction` | Chrome over a text selection (RADD-1395) | `EditorSelectionActionProps` `{editor, selection}` | the host places it; `selection` null ⇒ show no trigger | `components/editor/SelectionActions.tsx` |
| `contentReadAction` | An action on RENDERED content — a description, a comment, a page body (RADD-1395) | `ReadActionProps` `{text, context, transform?, subject, className?}` | shown for every reader; `transform` only when they may rewrite | `routes/item-detail.tsx`, `components/items/CommentsThread.tsx`, pages' `view/PageReading.tsx` |
| `contentBody` | How a rendered body — a description, a comment, a reply — is DRAWN when a plugin claims its record (RADD-1401) | `ContentBodyProps` `{text, record, context, canEdit, renderText}` | build it with `contentBody(spec)`; `claims(record)` decides and the first claimant draws — see "Content bodies" below | `components/editor/ContentBody.tsx` (used by the issue description, comments, replies and the requester's request view) |
| `issueTab` | Activity tab bar, next to VCS | `{item, project}` | needs `title` (+ optional `icon`); `render` = tab body | `components/items/ActivityPanel.tsx` |
| `viewHeader` | A view's header/toolbar | `{view, items}` | `items` = the view's loaded, permission-scoped issues | `routes/view.tsx` |
| `viewType` | A whole saved-view TYPE | `{view, items}` | `match` = the view_type key; pair with a `view_types=` manifest entry. A type declared a LIST surface needs no contribution — see "View types on the host's list" below | `routes/view.tsx` |
| `routePage` | A full page at a nav path | `ContributedPageProps` `{path, params}` | `match` = the pathname, or a pattern whose `$name` segments capture into `params` (RADD-1401) | `components/shell/PluginPage.tsx` (splat route) |
| `publicPage` | A page OUTSIDE the shell and the sign-in gate, under `/public/` (RADD-1401) | `ContributedPageProps` `{path, params}` | `match` = a path pattern (`/public/<plugin>/$token`); the visitor may be anonymous — see "Public pages" below | `components/shell/PublicPage.tsx` (root-level `/public/$` route) |
| `settingsPage` | A full page under Settings → … | `{path}` | `match` = the pathname | `components/shell/SettingsPluginPage.tsx` |
| `projectSettingsPage` | A whole page under a PROJECT's settings (RADD-1396) | `{project, path}` | `match` = the page's segment (`/p/<KEY>/settings/<segment>`); pair with `NavItemSpec(section="project_settings", path=<segment>)` — see "Project settings pages" below | `routes/project-settings/layout.tsx` (`ProjectSettingsPluginPage`, a splat under the project-settings route) |
| `settingsSection` | Into an *existing* settings page | `{}` | `match` = the page's key, which is its route segment under `/settings` — Settings → Plugins links a plugin with no page of its own to the pages its sections match (RADD-1380) | `routes/settings/timelogging.tsx` (`match="timelogging"`, Leave), `routes/settings/sign-in.tsx` (`match="sign-in"`, sso's providers); add anchors to other pages as needed |
| `profileSection` | The user's Profile page | `{}` | per-user prefs; drop `<UserContributionToggles>` here | `routes/settings/profile.tsx` |
| `pluginManagerSection` | A plugin's row in Settings → Plugins (admin) | `{plugin, pluginId}` | `match` = the plugin's registry name; drop `<GlobalContributionToggles>` here | `routes/settings/plugins.tsx` |
| `sidebarSection` | A folding section of the left sidebar (RADD-1392) | `{collapsed, onToggle}` | `match` = the section key the host placed (`pages`); render `SidebarSection` from the SDK | `components/shell/Sidebar.tsx` |
| `dashboardWidget` | A dashboard widget type | `{config, widget, filterQuery}` | `match` = the widget-type key; pair with a `widget_types=` manifest entry; `filterQuery` = the dashboard-wide SLQ filter (plugin widgets decide how to honor it); a `personal=True` type lands on My Work instead (RADD-1393) | `modules/dashboards/ui/src/WidgetBody.tsx` |
| `itemAttribute` | A list COLUMN and a board-card CELL (RADD-1394) | `{item, value, surface}` | `match` = the attribute id; build it with `itemAttribute(spec)` — see "Item attributes" below | `components/views/ColumnCells.tsx`, `components/board/card-cells.tsx` |
| `paletteMode` | A face of the command palette (RADD-1400) | `{report}` (the gate) | build it with `paletteMode(spec)`; the palette draws its entry row and its answer — see "Modes" below | `components/CommandPalette.tsx` |
| `queryInputMode` | An input mode of the query bar: free text in, SLQ out (RADD-1400) | `{report}` (the gate) | build it with `queryInputMode(spec)`; the bar draws the toggle — see "Modes" below | `components/views/QueryBar.tsx` |
| `automationNodeInspector` | The automation editor's inspector for YOUR node type (RADD-1325) | `AutomationNodeInspectorProps` (`{node, params, schema, onChange, …}`, exported by the SDK) | `match` = the node type (`AutomationNodeSpec.key`); with none registered the host renders a form generated from the node's `params_schema` | `server/src/radd/modules/automations/ui/src/GraphInspector.tsx` |

**Host components (RADD-1325).** An inspector should look and behave like the host's own forms
without bundling heavy editors. `@radd/plugin-sdk` exports `CodeEditor` and `TokenList`: thin
wrappers the host fills at boot via `provideHostComponents` (the SPA's CodeMirror, lazy-loaded;
the `{{token}}` picker). A plugin imports them from the SDK like any primitive; outside the host
they degrade to plain inputs. `SchemaForm` (the `params_schema` form) is the SDK's own since
RADD-1409 — it renders anywhere and is not a host-filled slot. The `ai` and `scripts` plugins'
inspectors are the worked examples (`modules/ai/ui`, `modules/scripts/ui`).

A plugin's settings PAGE reaches three more platform surfaces the same way (RADD-1377):
`ScopedSettings` (the settings-cascade editor for the `section` the plugin declared: effective
value, inherited/overridden, Reset), `RoleGrants` (a subject's role grants, as Users and Teams show
them) and `toast(message, kind)`. `useKeyedRows` (stable keys for removable row builders) is plain
SDK code. The names a remote can import are DERIVED from `packages/plugin-sdk/src/index.ts`
(`web/scripts/sdk-exports.mjs`); after adding an SDK export, run `node web/scripts/gen-shared-shims.mjs`.
The boundary test fails until the checked-in shim matches. These arrived in UI API 1.14.0; a remote
that uses them declares `ui_api_version="1.14.0"`.

UI API 1.15.0 (RADD-1393) added the shell surfaces the bundled dashboards package draws with:
`SlqField` (the SLQ editor with live validation; `onValidity` reports whether the draft parses),
`PageQueryFilter` (the top bar's SLQ filter, whose child receives the committed query), `ViewSelect`,
`SharingDialog` (the spec-57 sharing editor over a local draft; the plugin posts it to its own
endpoint), `ReportWidget` (the host's report cards as widgets), `ItemKeyLink`, `ItemPeek` (children
receive an opener for the peek panel) and `MissingPluginType`. It also added `ChartHeightContext`
(the plot height a dashboard widget grants its charts) and the `enabled` option on
`usePagedDirectory`. The host implements them in `web/src/host-surfaces.tsx`.

**Documents, comments and the kit (RADD-1392, UI API 1.15.0).** The wiki moved into the pages plugin's package, and it reaches the host's heavy surfaces the same way, with typed contracts beside each wrapper:
- `host-document.tsx` — `RichEditor` (`attachTo` names the attachment parent images go to; `binding` is an `EditorBinding` that makes the document a live copy, and its `key` keys the editor; `initialTransform` is a read action's hand-off), `RichViewer`, `Markdown`, `ReadingPane` (room beside the text for `useReadingPane`) and `EditorToolbarButton`. Until RADD-1395 this file also bridged `AiReadMenu`, `AiRun` and `AiResultsPane`, and until RADD-1397 `EditingNow` and `useLiveSession` (the host's co-editing client); the SDK names no feature now — those are the ai and collab plugins' contributions through the editor's extension points and live documents below.
- `host-comments.tsx` — `useCommentFeed` (a parent's section, newest window first), `CommentReplies`, `CommentComposer` (with `CommentComposerMode`), `CommentHistory`, `CopyCommentLink`, `ThreadBadge`/`ThreadFilter`/`ResolveThreadButton`, `useLinkedComment`/`useLandOnComment`/`useThreadExpansion`, `commentHref`, `repliesLabel`, `threadRuleClass`, `sendTaskToggle`, and the `CommentRow` shape.
  **The discussion model (RADD-1448), the same on issues, page discussions and inline annotations:** replies are visible by default (`useThreadExpansion` opens every comment except a resolved thread, and a reader's own choice survives refreshes until the resolution changes); the disclosure exists only over replies that exist, and `repliesLabel(row, expanded, canReply)` is its words ("Hide 3 replies", "Show 3 replies · resolved"; `canReply` no longer changes them). Replying is an ACTION, never the disclosure: pass `expansion` (and `actions`, e.g. a `ResolveThreadButton`) and mount `CommentReplies` under every comment — it draws the footer (disclosure, a Reply button, your actions), the replies, and the reply composer that one click on Reply opens under them, with one primary button; Cancel or Escape closes it and keeps the draft, posting closes and clears it. Without `expansion` it is the older block you mount only while your own toggle is open. `CommentComposer` is a discussion's composer: closed (`mode` null) it is a row of two buttons, Comment and Start thread; open, a Comment | Thread switch, your `controls` and editor, and ONE submit (`submitLabel` is yours, so it can name the audience) with a Cancel that keeps your draft.
- `host-kit.tsx` — `DropdownMenu`, `Popover`, `useDismiss` (the host's one Escape stack), `AccessGrantsEditor`, `ScopedAccess`, `StateCategoryDot`, and the sidebar chrome `SidebarSection`/`SidebarLink` for the new `sidebar.section` slot.
Hooks are bridged too: the host provides them before the first render, so every render calls the same function. Shared STATE lives in the SDK itself rather than behind a bridge: the `radd:*` registry (`registerPageExtension`, `PageExtensionCtx`, `MarkdownSourceContext`, `splitExtensionBlocks`…), `headingsOf`/`headingAnchorId`, text-quote anchoring (`makeAnchor`, `locateAnchor`, `orderByAnchor`) and the rendered-text helpers (`renderedText`, `rangeForOffsets`, `registerTextProjection`…). A bridged hook must return STABLE values: `useCommentFeed`'s list is memoised on the feed, because a fresh array per render re-ran the inline rail's anchor scan forever — and a render loop at default priority starves Suspense's retries, which read as lazy host surfaces that never finished loading.

The Leave plugin (`modules/leave/ui`) contributes its personal Leave form through `profile.section` and team Holidays through `settings.section` matched to `timelogging`. Neither settings page imports Leave components; disabling the remote withdraws both sections. Its avatar/name indicators and timesheet annotations are also plugin-owned data contributions; the host knows only the generic contracts described below.

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

## Shared settings contracts (SDK 1.3)

Plugin settings pages use the SDK's `SettingsPage`, `SelectField`, `Callout`, `QueryError`, `Button` and `TextField`. The host supplies generic implementations so the plugin retains the app's layout, accessibility, keyboard handling and permission-aware history link. The host component registry must never contain a feature page, feature-specific form or connector implementation. Date formatting also lives in the SDK singleton, preserving the reader's timezone across host and remotes.

The host installs its account-scoped API transport into the SDK. Host and remote requests share cancellation on account changes, the same `ApiError` class and error formatting. Capability hooks observe the host's `capabilities` query rather than a second cache; an unknown plugin is unavailable while discovery loads.

A navigation manifest entry may declare `group` (for example `Server`) and `requires_admin`, in addition to permission atoms. `/capabilities` attaches the owning `plugin`; generic navigation and page loading use that ownership. No per-plugin route/page mapping is needed. Settings links in the Plugins page prefer manifest entries.

Plugin pages show loading while their bundle activates, an unavailable message after withdrawal, and a failure message for incompatible/failed bundles or render exceptions. Imports/activation time out after 30 seconds. Render callbacks execute *inside* the slot boundary; a fresh registration resets a prior render failure. SDK compatibility requires a matching major and a host version at least as new as the remote's declared minimum.

## Data contributions (SDK 1.2)

Features that supply facts to shared views use `definePlugin({ dataSources: [...] })` rather than rendering slots or adding plugin checks to host pages. The loader tags each source with its owner and withdraws sources together with UI slots on disable or activation failure. Imperative activation can use `ctx.registerDataSource(source)` with the same lifecycle protection.

Two typed contracts are currently available:

- `personIndicators`: a shared signed-in lookup returning person ids and semantic status decorations (label, tooltip, accessible label, tone, optional dimming and plain-text suffix).
- `timesheetAnnotations`: a lookup for `{start, end}`, returning per-person calendar spans, status decorations and an explicit `suppressOutlier` policy. The timesheet clips spans to its window and composes annotations.

The feature owns `fetch(args, signal)`, endpoints, interpretation and refresh intervals. The host calls `usePluginData(kind, args, actorId)`. Query keys include plugin ownership, activation generation and actor id: data is shared between consumers without surviving as a visible contribution after disable or leaking between account identities. The query signal aborts an unused request when its source withdraws. Re-enabling gets a fresh query identity; a failed source contributes no initial data and cannot fail the surrounding host page. Mutation handlers call `invalidatePluginData(queryClient, pluginName)` to refresh their data consumers.

The Leave remote (`modules/leave/ui/src/data.ts`) is the first implementation. The host contains no Leave endpoint, label, date interpretation or enablement check. This is a data contract, not an invisible rendering component pretending to be a service.

## Item attributes: list columns and card cells (SDK 1.15)

A plugin adds a column to every list view and a cell to the board card designer with ONE
declaration. It is not a new registry: `itemAttribute(spec)` returns an ordinary contribution to
`SlotId.itemAttribute` (so plugin tagging, withdrawal, the per-contribution toggles and the error
boundary come with it), and its data is one of the plugin's own `querySources` (so shared query
keys, activation generations and abort-on-withdrawal come with that).

```tsx
import { definePlugin, itemAttribute, api, type QuerySource } from "@radd/plugin-sdk";

const timers: QuerySource<Record<string, Timer[]>> = {
  key: "slas.timers",                                   // `<plugin>.<name>`, like every query source
  meta: { entities: ["item", "slaPolicy"] },            // refreshed with the entities it caches
  refetchInterval: 60_000,                              // a countdown changes with the clock
  fetch: ({ ids }, signal) => api.post("/items/sla/batch", { item_ids: ids }, { signal }),
};

export default definePlugin({
  querySources: [timers],
  contributions: [
    itemAttribute<Timer[]>({
      id: "slas.timer",          // what saved views and card layouts store
      label: "SLA", width: 96, minWidth: 56,
      source: timers.key,        // one of THIS plugin's query sources
      sample: [aHealthyTimer],   // what the card designer's preview draws
      render: ({ value, item, surface }) => <SlaRowChip timers={value} />,
    }),
  ],
});
```

The contract:

- **The id is `<plugin>.<name>`** of the registering plugin, and so is `source`. Anything else —
  a builtin name, a `cf.<key>`, a bare word, another plugin's prefix — is skipped by
  `useItemAttributes()`, and cells render through `<Slot owner=…>`, so a second plugin that
  registers the same key cannot draw into the owner's cells.
- **The host asks once per page of rows.** For each attribute shown as a list column or placed on
  the card, the page's items are cut into stable batches of at most `ITEM_ATTRIBUTE_BATCH_MAX`
  (200) ids; `fetch({ids}, signal)` resolves to `{[itemId]: value}` for the ids that HAVE a value.
  One request per (source, batch) is shared by the list, the board and swimlanes (and by
  attributes that share a source); appending a page asks only for the new ids.
- **`render` only sees a value.** An item the batch did not answer shows the host's empty
  treatment — a dash in lists, no cell on cards — so a lane of empty cells collapses exactly as it
  does for builtins. `surface` (`"list"`/`"card"`) lets a chip size itself.
- **Withdrawal degrades like a deleted custom field.** Disabling the plugin removes the column,
  the card cell and the palette entry live and aborts an in-flight batch; the saved view keeps the
  id, the list skips it, the Columns editor shows `<id> (unavailable)`, and the card designer's
  stale note names it. Re-enabling reads afresh.

The slas plugin is the first adopter (`modules/slas/ui`): the SLA column, the card cell and the
issue rail's SLA section are its own — and, since RADD-1396, its settings page and queue view type;
the host holds no SLA code. Remotes that use this declare `ui_api_version="1.15.0"` (1.16.0 for the
project-settings page slot).

## Project settings pages (SDK 1.16)

A plugin owns a page under a project's settings the way it owns one under Settings: a manifest nav
entry lists it, a slot contribution draws it. The slas plugin's SLAs page is the first
(`modules/slas/ui/src/settings/`).

```python
from radd.sdk import NavItemSpec, NavSection
NavItemSpec(key="sla", label="SLAs", path="sla", icon="timer", order=70,
            section=NavSection.PROJECT_SETTINGS, requires=("sla.update",))
```

```tsx
{ id: "settings", slot: SlotId.projectSettingsPage, match: "sla", label: "Project SLA settings page",
  render: (props) => <SlaSettingsPage project={(props as ProjectSettingsPageProps).project} /> }
```

- **`path` is a SEGMENT**, not an absolute path: the page lives at `/p/<KEY>/settings/<path>` for
  every project, and the contribution's `match` is the same segment. The host's sections win over it.
- **`requires` atoms are checked IN the project** (`usePermissions().project(project, atom)`), so a
  project's Manager sees the entry where they hold the atom. The endpoint still enforces its own
  authorization; the nav gate is presentation.
- One list — the host's sections plus the contributed ones, at their `order` (the host's are
  0, 10, … 60) — feeds the sub-nav, the index redirect and the sidebar's Settings link
  (`lib/project-settings-nav.ts`), so a person who can manage only a plugin's page still gets there.
- The page gets `{ project, path }`; `project.permissions` answers the SDK's permission checks.
  Disabling the plugin removes the entry and turns a direct visit into the generic unavailable
  notice; a turned-off contribution drops the entry too.

## View types on the host's list (RADD-1396)

A view type whose rows are items in a particular ORDER needs no surface of its own. Declare it a
list surface and the host's list draws it — selection, bulk actions, columns, paging, the SLQ bar
and quick filters come with it — over the plugin's rows:

```python
ViewTypeSpec(key="slas.queue", label="Queue (triage list)", icon="list-ordered",
             sidebar_section="Queues",
             list_surface=ViewListSpec(rows_path="/sla-queue-items",
                                       columns=("type", "reporter", "priority", "slas.timer", "state"),
                                       refresh_seconds=60))
```

- `rows_path` answers the `/items` paging contract (`q`, `project_id`, `limit`, `offset` → an
  `ItemRead` list) in the plugin's order. A type with its own rows owns that order, so it is never
  drag-ranked; the list's count and "select all" still use `/items/count` and `/items/ids`.
- `columns` seed a new view (a saved `columns` wins); `refresh_seconds` re-reads the rows while open.
  A list-surface type is flat — whatever axes a view stored are ignored.
- `sidebar_section` lists the type's views in a sidebar section of their own, each with a live count
  (`POST /views/counts`), and leaves them out of the ordinary view lists (`GET /views?sectioned=false`).
- `icon` names a `lib/icons.ts` entry; the header, pins and sidebar rows draw it.
- With the plugin disabled the type is unknown: a saved view shows `MissingPluginType`, fetches no
  rows, and is listed among the ordinary views again so it stays reachable.

**Cache tags.** A shared entity (an item, a project, a role…) is tagged with the SDK's `Entity`
member — `meta: entityMeta(Entity.item, Entity.project)` — the one vocabulary the host's realtime
map and every plugin UI spell (RADD-1467). **Realtime for a plugin's own entities.** Tag a query
with the SERVER's entity type verbatim — `meta: { entities: ["sla_policy"] }` — and invalidate with
the SDK's `invalidateEntities(queryClient, "sla_policy")`. The host's realtime subscribes every tag
it does not map itself as that exact server string, so a plugin needs no host table row for its
entities to go live.

## The editor's extension points (SDK 1.16)

The rich editor — Milkdown/ProseMirror, its toolbar, the per-block diff review, CodeMirror code
blocks, `radd:*` nodes — is HOST code that issues, comments and the wiki share. A plugin extends it
through three slots and two mechanisms — a transform, and a binding (below, RADD-1397); none of
them names a feature (RADD-1395). The types live in `packages/plugin-sdk/src/editor-extensions.ts`.

```tsx
import { Megaphone } from "lucide-react";
import { definePlugin, EditorToolbarButton, SlotId, type EditorToolbarActionProps,
  type EditorTransform } from "@radd/plugin-sdk";

const shout: EditorTransform = {
  label: "Shout",
  emptyMessage: "Nothing to shout.",
  run: async ({ document, selection }, { signal, onText }) => {
    const text = (selection || document).toUpperCase();   // stream from your endpoint instead
    onText(text);                                           // the replacement SO FAR, not a chunk
    return signal.aborted ? null : { replacement: text, notes: [] };
  },
};

function ShoutButton({ editor }: EditorToolbarActionProps) {
  return <EditorToolbarButton icon={<Megaphone size={16} aria-hidden />} title="Shout"
    disabled={editor.busy} onPick={() => editor.transform(shout)} />;
}

export default definePlugin({
  contributions: [{ id: "shout", slot: SlotId.editorToolbarAction, render: (p) => <ShoutButton {...(p as EditorToolbarActionProps)} /> }],
});
```

- **`editor.toolbar.action`** — props `{ editor }`. Render a button (`EditorToolbarButton` draws it
  like the host's own and keeps the editor's selection on press). Render `null` to offer nothing: a
  contribution's own gate (a feature toggle, a user preference) decides. Popovers are the
  contribution's (portal them).
- **`editor.selection.action`** — props `{ editor, selection }`. The host PLACES the anchor above
  the selection and keeps it mounted while the editor is idle; `selection` (`{from, to, left, top,
  bottom}`) is null while nothing is selected or the editor lost focus. Opening a prompt field moves
  focus and collapses the selection, so CAPTURE `selection` when your chrome opens and pass that
  range to `editor.transform` — reading the live selection later silently widens the run to the
  whole document. Nothing is offered while `editor.busy`.
- **`content.read.action`** — props `{ text, context, transform?, subject, className? }` on
  RENDERED content, for every reader. `context` says what the content is: `{entityType, entityId,
  parent?}` — an issue's content is its description (`item`), a comment names its `parent`, a page
  is `page`. `transform` is present only when the reader may rewrite it: calling it opens the
  editor, which runs your transform first (`RichEditorProps.initialTransform`). `subject` ("the
  description", "this comment") is for accessible names; `className` is the host's placement for
  your trigger (a reveal on hover).
- **A transform** — `editor.transform(transform, range?)`. `run(input, {signal, onText})` receives
  `{document, selection}` as markdown (`selection` is "" for a document-wide run) and resolves
  `{replacement, notes?}`; the editor splices the replacement over the range, shows its run band
  (label, live preview, Stop), then its per-block review with Accept all / Reject all, the notes,
  and — where the document carries inline comments — the passages the replacement would strand.
  Resolve `null` for a withdrawn run; reject with a presentable error (its message is shown);
  `emptyMessage` is said when nothing changed. Whatever must survive the round trip is the
  transform's business: the ai plugin masks `radd:*` fences, images and attachment links behind
  placeholders and restores them (RADD-1274) — the editor never learns there was a mask.
- **The reading pane** — `useReadingPane()` returns `open({title, label?, icon?, render})` on a
  surface with room beside its text (the issue page; a wiki page, which wraps itself in the
  `ReadingPane` bridge), else null: answer in place then. The frame is the host's; each open renders
  `render()` afresh; a panel opened from your contribution closes when your plugin is withdrawn.
- **`IssueSuggestion`** — the host's row for a suggested issue (peek-aware link, preview on a
  resting pointer, optional `badge`/`note`, and `mergeFrom` for the merge-this-duplicate action).

The ai plugin is the worked example (`modules/ai/ui`): the toolbar button and Ask AI over a
selection (`editor/`), the read menu (`read/`), answers in the reading pane (`results/`), the issue
rail's card (`issue.rail.top`), Similar issues beside a draft (`item.draft.assist`) and its Profile
opt-out — and, since RADD-1400, the palette's Ask and the query bar's natural language (see "Modes"
below), so the host names no AI at all. Disabling it withdraws every one of them live — from an open editor too — and its
`deactivate()` stops any run in flight. Remotes that use these declare `ui_api_version="1.16.0"`.

## Live documents and editor bindings (SDK 1.17)

A document surface can be edited by several people at once without the host knowing how. Two
contracts, both feature-neutral (RADD-1397); the collab plugin (`modules/collab/ui`) is the worked
example, and with it disabled the host ships and loads none of its code.

**Live documents — "is a live session available for this document?"** The surface asks with
`useLiveDocument({ entityType, entityId, canWrite, editing, getMarkdown, save })`; a plugin answers by
contributing a source (`definePlugin({ liveDocuments: [source] })`, or `ctx.registerLiveDocumentSource`):

```tsx
const pages: LiveDocumentSource = {
  id: "collab.pages", entityType: "page",               // one provider per entity type
  open: (request, update) => {                          // request.viewer is always a signed-in account
    update({ status: "joining", role: "editor", binding: null, presence: <Who store={s} /> });
    // …later: update({ status: "live", role, binding, presence, saving })
    return { finish: async () => { /* the last save */ }, close: () => { /* leave */ } };
  },
};
```

- **What the surface owns:** the document — its endpoint, its body, its Save. `save(markdown, {session,
  final, keepalive})` is the surface's own write, and `session` is the session's VOUCHER (the wiki
  sends it as `collab_session`, which the collab write guard admits without a version check). The
  session decides WHEN and by which client; it never learns the endpoint.
- **What the session owns:** who is here (`presence`, rendered in the header for readers too), the
  editor binding for editors, the chrome beside Done (`saving`), and `finish()` — the last save.
  Chrome is rendered inside the same error boundary and owner context a slot contribution gets.
- **The answer** (`LiveDocument`): `status` is `none` (no provider, a refusal, a visitor — run the
  ordinary flow), `joining` or `live`. No provider is `none` at once, even while plugin bundles are
  still loading: an optional plugin never holds up the document's own editor. The session reopens
  when the document, `editing`, `canWrite` or the viewer changes; it closes on unmount and when the
  provider is withdrawn, the saving client's last write first.

**Editor bindings — a live copy of the editor's document.** `RichEditor`'s `binding` takes an
`EditorBinding` (`{ key, label, bind(editor, signal) }`). Bound, the editor refuses input until
`bind` resolves, drops its own history (the binding brings the undo a shared document needs),
offers no plain-text mode (`label` takes the switch's place), and publishes every document change
through `onChange` from the CURRENT document — the binding's changes included, which ProseMirror
marks as outside the history and Milkdown's listener skips. `bind` receives a `BindableEditor` —
`view` (ProseMirror's `EditorView`), `markdown` (what to seed an empty copy from), `parse(markdown)`
and `addPlugins(plugins)` (returns the remover) — and resolves the unbind, which the editor runs
before it is destroyed.

**The editor runtime is a shared singleton, loaded on demand.** A binding's ProseMirror plugins must
be built from the HOST's `prosemirror-model`, `prosemirror-state` and `prosemirror-view`: a bundled
copy's plugin keys, `instanceof` checks and node classes do not match the editor's. The import map
maps those three to shims that load the host's own instances with the editor (a top-level await on a
loader the host registers), so importing them costs nothing until an editor exists — keep that code
in a chunk you import when binding. Libraries on top (y-prosemirror) bundle normally and pick up the
shared modules through the import map. Anything that never crosses into the editor stays private to
the plugin: collab's yjs is its own, because no host code ever touches a Y.Doc. Remotes that use
this declare `ui_api_version="1.17.0"`.

## Modes: the command palette and the query bar (SDK 1.18)

Two host surfaces take MODES a plugin contributes (RADD-1400): the command palette (another face,
answering what is typed) and the query bar (another way to fill the SLQ editor). Each is a slot
contribution built by an SDK helper — plugin tagging, withdrawal, the per-contribution toggles and
the error boundary come with it. The ai plugin is the worked example: the palette's Ask
(`modules/ai/ui/src/palette/ask.ts`) and the bar's natural language (`query-bar/natural-language.ts`).

```tsx
import { Sparkles } from "lucide-react";
import { api, definePlugin, paletteMode, queryInputMode } from "@radd/plugin-sdk";

export default definePlugin({
  contributions: [
    paletteMode({
      id: "notes.find", label: "Notes", hint: "search my notes", icon: Sparkles,
      placeholder: "Search notes…", prompt: "Type to search your notes.",
      useAvailable: () => useNotesEnabled(),          // a HOOK; absent = always offered
      answer: async (query, { signal }) => ({          // or { text } — see below
        heading: "Notes",
        rows: (await api.get<Note[]>("/notes", { signal, query: { q: query } }))
          .map((n) => ({ id: n.id, title: n.title, hint: n.when, href: `/issues/${n.item_key}` })),
        empty: "No note says that.",
      }),
    }),
    queryInputMode({
      id: "notes.title", label: "Title", hint: "issues whose title says it", icon: Sparkles,
      placeholder: "Words from a title — the answer lands as SLQ",
      dialects: ["items"],                             // default: every dialect
      toQuery: async (text) => ({ query: `title ~ ${JSON.stringify(text)}`, explanation: "Issues whose title mentions it." }),
    }),
  ],
});
```

**What every mode declares** (`ModeSpec`): `id` — `<plugin>.<name>` of the registering plugin, any
other prefix is refused; `label` and `hint`, which the host draws; an optional `icon` (a component —
any lucide icon — the host sizes and colours); and `useAvailable`, a React HOOK. The surface mounts
each mode's GATE (the contribution's `render`) while it is open and the gate calls the hook, so it
may read queries and preferences like any component: a mode is offered only while its gate says so.
A withdrawn plugin's gate unmounts and its mode disappears; a gate that throws is quarantined and
its mode is never offered. The host draws every trigger itself, because it owns the keyboard.

**`palette.mode`** — `paletteMode(spec)`. With something typed, each available mode trails the
palette's list as "`label`: “query” — `hint`"; choosing it switches the palette's FACE (it never
closes), Esc or the back arrow return to search. In the mode, `placeholder` is the input's,
`prompt` is said while nothing is typed, and the debounced, trimmed query goes to
`answer(query, { signal, onText })`:
- **rows** — `{ rows, heading?, empty? }`, each `PaletteRow { id, title, href, badge?, icon?,
  subtitle?, hint? }`. The palette draws them as its own rows (a `badge` in the key pill, a trailing
  faint `hint`), moves through them with the arrows and follows `href` — a site-relative address —
  through the router, no reload. `empty` is said when there are none.
- **text** — `{ text, heading? }`. Call `onText(textSoFar)` while it streams (the whole text so far,
  not a chunk); the palette shows it as it grows.
- `signal` aborts when the query changes, the palette closes or the plugin is withdrawn; a rejection's
  message is shown (`busyLabel` is said while the first answer is on its way). The answer is ONE
  query per (mode, query), keyed under the owner's name, so withdrawal drops it; while the next
  answer loads the previous one stays — only the same mode's.

**`query.input.mode`** — `queryInputMode(spec)`. The query bar's own mode is SLQ. With any mode
available for the bar's dialect it shows a `SLQ | label…` toggle, mod+I cycles SLQ → each mode →
SLQ, and an EMPTY bar opens on the first available mode; a bar that arrives with a query (the URL
carries the committed one) opens in SLQ, so the applied query stays visible, and an explicit switch
sticks. With none, the bar is plain SLQ and has no toggle. In the mode the input shows
`placeholder` (named `ariaLabel`), and Enter calls `toQuery(text, { dialect, signal })`:
- `dialect` is the SLQ dialect the bar queries — `QueryDialect.items`, or `QueryDialect.worklog` on
  the timesheet (spec 98: a worklog query reaches issue fields through `issue.`). `dialects` lists
  the ones a mode can write; it is not offered elsewhere.
- Resolve `{ query, explanation }`: the bar puts the query in its SLQ editor and APPLIES it, and
  shows the explanation under the bar until the query is edited — every answer is visible SLQ. There
  is no auto-detection: a mistyped query fails as SLQ, it never becomes a mode's input.
- Reject with a presentable error (its message is shown under the bar; `busyLabel` while waiting).
  `signal` aborts when the bar goes away or the plugin is withdrawn, and a draft that arrives after
  either is dropped.

Remotes that use these declare `ui_api_version="1.18.0"`.

## Public pages and page patterns (SDK 1.19)

A page's `match` may be a PATTERN (RADD-1401): a `$name` segment captures exactly one non-empty
path segment, and the page receives the captures, decoded, as `params` beside `path`
(`ContributedPageProps`). A literal match wins over a pattern; among patterns, the first in the
slot's order. `matchPagePath(pattern, path)` is the one matcher (the host's page mounts and the
turned-off check both use it) and `usePageMatch(slot, path)` the hook. It works for every page slot —
`route.page`, `settings.page` and the new one below.

**`public.page`** is a page for someone who holds a LINK rather than an account — a tokened link in
an email. The host mounts `/public/$` at the ROOT of the route tree, beside `/login`: no shell, no
sign-in gate. It draws only the frame (the brand and a reading column) and runs the plugin loader
itself, since the shell that normally does is not mounted. Before rendering, the route resolves the
visitor and puts the api client in visitor mode, so on these pages a 401 is a refusal to show, never
a redirect to sign in. What an anonymous visitor loads is exactly what spec 121's visitor shell
already loads — `/capabilities` and the enabled remotes, both answered for the Anyone principal (the
frozen inventory in `tests/test_anonymous_surface.py` is unchanged) — so a public page leaks nothing
the visitor shell did not. The page's own endpoints must be the plugin's unauthenticated router,
where the token is the credential.

```tsx
{ id: "survey", slot: SlotId.publicPage, match: "/public/csat/$token", toggleable: false,
  render: (props) => <SurveyPage token={(props as ContributedPageProps).params.token} /> }
```

The csat plugin's rating page is the first (`modules/csat/ui/src/SurveyPage.tsx`): the survey email's
links land on it, `?rating=N` preselects a star (a page owns its search params; read them with the
router's `useSearch({ strict: false })`). Mark such a page `toggleable: false`: it is where the
plugin's own emails land, and a visitor has no toggles to read — disabling the plugin is how it
goes, and then the link shows the host's "unavailable" notice.

The sign-in page is NOT a public page and stays the host's (RADD-1380): it is the way in, so it must
not wait on, or break with, optional plugin code, and it mounts no plugin loader.

## Content bodies (SDK 1.19)

The host draws every rendered body — an issue's description, a comment, a reply, a requester's view
of either — with its own viewer. A plugin that knows something about SOME bodies claims them by the
record they came from and draws them instead (RADD-1401):

```tsx
import { contentBody, type ContentBodyProps } from "@radd/plugin-sdk";

export const signedBody = contentBody({
  id: "mailintake.signature",                                        // `<plugin>.<name>`
  label: "Folded email signatures",
  claims: (record) => typeof (record as { email_signature?: unknown }).email_signature === "string",
  render: ({ text, record, context, canEdit, renderText }: ContentBodyProps) => <SignedBody … />,
});
```

- **`claims(record)`** is called for every body the host renders: keep it a cheap, pure read of the
  record, as the server sent it. A throw counts as no. The first registered, turned-on claimant (in
  `order`) draws; the host names none of them and knows nothing that makes a body special.
- **`renderText(text)`** draws markdown exactly as the host draws this body — its viewer, deferred
  mounting, mentions and checklists. A LEADING part of the body keeps its task checkboxes live; any
  other part is drawn read-only, since its tasks are not counted from the body's start.
- `context` is `{entityType, entityId, parent?}` (an issue's description is `item`; a comment names
  its parent); `canEdit` says whether this reader may change the content (its author, someone who
  runs the project) — the plugin's own endpoint still enforces it.
- **Nothing is ever lost to a plugin.** With no claimant, the claimant's plugin withdrawn, or its
  render throwing, the body is the host's ordinary markdown.

The mailintake plugin is the first (`modules/mailintake/ui/src/SignedBody.tsx`): intake records a
mailed body's signature as `email_signature`, an annotation over an exact suffix of the stored text,
and the claim folds it under "Show signature", with "Not a signature" for someone who may edit the
content. There is no `origin` on the wire that marks a mailed body — `comments.origin` is
deliberately NULL for a person's mailed reply (RADD-1318) and items carry none — so the annotation
itself is what the claim reads.

Remotes that use either declared `ui_api_version="1.19.0"` when they shipped; see 2.0.0 below.

## SDK 2.0.0 (RADD-1465): the removed exports

The first MAJOR. `isUiApiCompatible` refuses a remote whose declared major differs, so a remote
built against any 1.x is refused by a 2.x host, and vice versa; every in-repo remote and
`examples/acme-notes` declare `ui_api_version="2.0.0"`, and a remote that declares nothing is taken
to need the current contract (`DEFAULT_UI_API_VERSION` in `modules/capabilities/router.py`). What
went, and where its job lives now:

- `paletteAnswerQuery` — the palette's answer query is internal to `usePaletteAnswer`
  (`palette-modes.ts`); a mode supplies `answer`, the SDK runs it.
- `ANCHOR_CONTEXT_CHARS` — a private constant of `anchoring.ts`; `makeAnchor` decides the context.
- `textNodesOf` — a private helper of `dom-text.ts`; the exported `renderedText`,
  `rangeForOffsets` and `offsetsForSelection` walk the nodes for the caller.
- `SlotId.sidebarNav` (`sidebar.nav`) — sidebar entries come from the backend manifest's
  `NavItemSpec`, never from a UI slot; a folding section is `SlotId.sidebarSection`.
- `SlotId.itemAction` (`item.action`) — an item's actions are contributed commands
  (`registerCommandSource` in `commands.ts`, read by the issue's quick actions through
  `useContributedCommands`).
- `HostComponents.SchemaForm` — `SchemaForm` is the SDK's own component (RADD-1409, above), so the
  host no longer provides one at boot; `provideHostComponents` fills `CodeEditor`, `TokenList`,
  `ScopedSettings` and `RoleGrants`.

**Named exception (RADD-1401).** The issue's History tab (`components/items/HistoryTab.tsx`) still
words `csat.*` and `mail.*` events itself. It is a ledger: one switch words every plugin's events
(approvals, participants, vcs, worklogs as well), and an event outlives the plugin that emitted it,
so a disabled plugin's past rows must still read as sentences. Contributed event sentences are one
mechanism for every plugin, not a csat or mail move; `plugin-boundaries.test.mjs` names the file
and fails once it no longer needs the exception.

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
plugin renders it via the `view.type` / `dashboard.widget` slot (matched by the key). A widget with
settings contributes its form to `dashboard.widget.config` (matched by the key; props
`DashboardWidgetConfigProps`: the config bag, `onChange`, `onValidity`) — the host's Add/Edit widget
dialog draws it in place of its own fields — and names a pydantic `config_model` on the
`WidgetTypeSpec`, which dashboards validates every write against (422), as it does for its own types
(slas' "Service desk SLA" report widget is the worked example, RADD-1462). A widget that
shows the viewer's OWN work is a **My Work widget**: `WidgetTypeSpec(key, label, personal=True,
suggest=…)` — offered only in My Work's picker, refused on shared dashboards, and put on a person's
suggested layout whenever the async `suggest(session, user)` answers True (approvals' "Awaiting my
approval" is the worked example, RADD-1393). Disabling the plugin withdraws the type and its slot
together; a widget already on a layout keeps its place and reads "no longer available" until the
plugin returns (`tests/test_my_work_contributed_widgets.py`). The example ships
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
    tsconfig.json              # { "extends": "@radd/plugin-sdk/tsconfig.plugin.json", "include": ["src"] } — nothing else
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
        ui_api_version="2.0.0",                              # host version-gates this (the SDK major)
    ),
)
```

A nav item's `icon` is a kebab-case name from the host's one icon registry, `web/src/lib/icons.ts`:
`"zap"`, `"folder-tree"`, `"database-zap"` and so on (RADD-1390). A name it doesn't ship draws a
visible placeholder, and a boundary test refuses a manifest that declares one. A plugin whose settings
page renders its own `SettingSpec`s declares `page_scopes=("instance",)` (or `"project"`) on each,
so Settings → General leaves those rows out. No host list names the section.

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
then enable it in **Settings → Plugins** — its UI and backend contributions activate at runtime; wait for Applying to finish.

---

## Boundaries

- Core plugins' UI is bundled into the host and registered at boot; optional plugins' UI is a
  runtime remote (RADD-1373). Both contribute only through slots and the SDK.
- View and widget types are backend registries (`registries.view_types` / `widget_types`, from
  `ViewTypeSpec` / `WidgetTypeSpec`); the `viewType` / `dashboardWidget` slots are their UI half.

Settings pages may host other plugins' sections with `<Slot id={SlotId.settingsSection} match="monitoring" />`. A contribution owns its data request as well as its UI. Use shared, stable query keys and the SDK's normal stale times (`useContributedQueries`, `usePluginData` and the directory controls default to 30s): two surfaces reading the same rows then share one request, and a page revisited within the window renders from cache. Do not set `gcTime: 0` / `staleTime: 0` to "abort on withdrawal" — the loader already drops a withdrawn optional plugin's cache and aborts its in-flight reads (RADD-1345, RADD-1377), and a zero window only makes every mount refetch. Consume the query `signal` so an aborted read stops. Mutations already accepted by the backend may finish; do not discard saved configuration on disable. Navigation requirements are presentation gates; the owning endpoint must enforce authorization too.

Built-in remotes use the shared Tailwind sheet, whose source scan includes every module's `ui/src` directory. External bundles should use SDK primitives/tokens or supply their own styles; adding a plugin must never require a named entry in the host stylesheet.


## Owner-contributed directories (SDK 1.4)

`DirectorySelect` resolves a provider's `directory.select` contribution by `source` and forwards its value, selection callback, labels, disabled state and optional string context. The SDK does not know the directory's entities or endpoints. Auth contributes `auth.people`; Teams contributes `teams.teams` and `teams.candidates` (context: `teamId`, `purpose` = member/manager/owner). These are public UI contribution contracts, not host-provided feature components.

The provider can use `PagedDirectorySelect` for the shared searchable/paged dialog. It supplies a query factory returning the query key, entity metadata and abortable query function. The shared `api.getPaged<T>` preserves `X-Total-Count` as `{rows, total}` using the host's account-scoped transport. Generic Modal, ListSearchInput and DirectoryPager adapters reuse the host's accessible controls. Each dialog has its own query lifetime; closing, changing source/context or withdrawing the provider unmounts it, aborts unused reads and discards its cache. Selected values belong to the caller and survive an unavailable provider. Missing/failed providers render a disabled, explicitly unavailable control.

Auth/Teams remain required core modules; these tests do not imply the plugin manager can disable them. Missing/failed/withdrawn frontend contributions are exercised independently. Auth and Teams are core plugins; callers use `DirectorySelect` directly.

## Owner contracts (SDK 1.5–1.12)

An owner publishes its slot ids and props in a contract file its package exports
(`@radd-plugin-ui/<plugin>/<name>-contract`); callers pass data and callbacks, and the owner draws.
Every mounted control owns its query identity and abort signal and keeps no unused cache. When the
owner withdraws, its controls, open pickers and in-flight reads go away while the CALLER keeps its
saved values; re-enabling resolves them fresh. Aborting a transport never rolls back a write the
server already accepted — reopening reads server state again.

- **1.5 — schema forms and code.** `SchemaForm` + `defaultsFromSchema` render scalar values, typed
  enums and boolean groups, and preserve unknown saved enum values, unnamed fields and unsupported
  structures (shown as JSON; they need an owner editor). It is not a JSON-schema editor or validator:
  the server still validates. `CodeEditor` is the host's lazy CodeMirror; the caller picks the language.
- **1.6 — option directories.** `optionContribution` registers a `directory.options` source: an opaque
  source name, a noun, row presentation, cache metadata, a paged fetch and saved-value resolution, with
  scope forwarded to both. `OptionChoices`, `OptionSelect`, `OptionTextField` and `OptionNameValues` are
  the generic controls. Auth, Teams, Workflow, Itemtypes, Releases, Forms, Pages and Groups provide the
  sources. Text and token inputs stay editable with the provider missing, and a disabled browser never
  authorizes a fetch — the server checks every request.
- **1.7 — project and cycle pickers.** Projects contributes `projects.select`/`projects.picker`, Cycles
  `cycles.select`/`cycles.choices` (their `ui/src/picker-contract.ts`); the SDK adds `usePagedDirectory`
  and `Switch`. Changing project context resets an open cycle picker to that project's scope.
- **1.8 — field controls.** Fields contributes `fields.form` and `fields.control`
  (`fields/ui/src/control-contract.ts`): callers supply definitions, values, errors, lock rules and
  callbacks, and the controls make no registry requests. A removed select option shows as an explicit
  unavailable option and an unsupported type as a disabled saved value — neither disappears. The SDK
  adds `TokenMultiSelect` and `ErrorText`. Teams' relationship pickers
  (`teams.relationship.select|choices|audience`, labels resolved in windows of at most 50 ids) ride the
  same contracts.
- **1.9 — query sources.** `PluginModule.querySources` / `ctx.registerQuerySource` register
  `{key, meta?, fetch(args, signal)}`. A key must start with the registering plugin's name and a dot, so
  no other plugin can claim it even while the owner is absent. Consumers call
  `useContributedQuery(key, args, {enabled})` and read `available` apart from pending/error; a disabled
  or absent source never issues a request, even on an explicit refetch. Fields, Labels, Items, Pages and
  Projects provide sources.
- **1.10 — schedules.** `ScheduleConfig`, `ScheduleKind`, `defaultSchedule`, `isScheduleValid` (form
  completeness only), `SchedulePreview` and `ScheduleEditor` (`value`, `onChange`, a stable
  `previewSchedule(config, signal)`). Backup contributes its editor to `backup.schedule.editor`, and
  Automations draws one inside its own package; each has its own preview endpoint, both computed by
  `radd.schedule_preview`.
  Previews debounce 350 ms and abort superseded requests, and an A→B→A edit gets a fresh preview.
- **1.11 — change presentation and history.** `ChangeList`/`ChangeLine` render the backend's
  structured-change shape (scalar changes, collection deltas, withheld values — stripped before any
  `entity.change.line` contribution, matched by entity type, sees them); `entity.change.fields` offers
  field suggestions. Audit contributes `settings.footer` (`{history: {entities?, projectId?}}`) and
  `entity.history` (`{entityType, entityId, projectId?, title?}`). Also `CollapsibleCard`, `DateField`,
  `Pager`, the table primitives and `TableSkeleton`. A nav entry may declare `requires_any_project`
  (each atom held in at least one project) — an availability hint; the destination API enforces the
  exact scope.
- **1.12 — contextual commands.** `PluginModule.commandSources` entries are
  `{id, entityType, meta?, list(context, signal), execute(id, context, signal)}` with context
  `{entityType, entityId, projectId?}`; consumers call `useContributedCommands(context, enabled)`.
  Retained callbacks refuse after withdrawal, removal aborts an active execution, and a successful
  command invalidates visible queries; an owner calls `invalidatePluginCommands(client, plugin)` after
  its own configuration changes. Automations' manual actions use it.

**Contract-only packages.** A package may export contract entry points (slot ids and types, no
implementation); a consumer declares the package dependency, the build links declared packages before
type-checking and refuses to replace a real installed package, and the boundary test forbids
implementation code in them. Such a package may have no Vite entry at all (Comments' visibility
vocabulary).

## Transition-rule editors and VCS connector tabs

- **Workflow transition rules (RADD-1383).** `@radd-plugin-ui/workflow/transition-rule-contract`
  exports the slot `workflow.transition.rule` and `TransitionRuleEditorProps` (the row's rules,
  `onChange(check, params | null)`, `canManage`, `saving` — not `pending`, which `<Slot>` keeps as its
  own prop). The host's transitions editor renders the slot on every row after its own rules, and uses
  each contribution's `match` (its check key) to tell a served rule from one whose plugin is gone: that
  one shows a fail-closed notice with Remove, because the server refuses every move it governs.
  Approvals' "Require approval" is the worked example (`approval-rule-editor-proof.mjs`).
- **VCS connectors (RADD-1366, reshaped by RADD-1435).** VCS owns `/settings/vcs` and draws one tab per
  loaded connector from `GET /vcs/connectors` (global.manage); a connector ships no UI. Its wording
  (title, description, webhook and token guidance, what a change is called) comes from the
  `ConnectorSpec` the connector's Python manifest provides on the `vcs_connector` socket, and REST
  paths, cache tags and audited entity types follow from the provider key by one VCS convention.
  Disabling a connector removes its tab on the next refetch; no connector bundle is ever requested
  (`browser-vcs-settings.mjs`).
