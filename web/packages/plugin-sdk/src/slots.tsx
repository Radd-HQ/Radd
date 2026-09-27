import { useRemotesLoading } from "./remote-loading";
import {
  Component,
  createContext,
  useContext,
  useMemo,
  useSyncExternalStore,
  type ErrorInfo,
  type ReactNode,
} from "react";
import { api } from "./api";
import type { PluginContribution } from "./plugin";
import { Switch } from "./switch";

/** The user-preferences key under which the PER-USER disabled-contribution set is stored
 *  server-side (`GET/PUT /auth/me/preferences`). */
const PREF_KEY = "disabled_contributions";

/**
 * The slot registry — the seam between the host shell and plugin UI. Base views render
 * `<Slot id=…>` and know no plugin; a remote calls `registerSlot`. A federation SINGLETON, so a
 * remote's registration lands in the store the host's `<Slot>` reads; `unregisterPlugin` withdraws
 * a plugin's contributions live. A new extension point is a `SlotId` plus a `<Slot>` in the host.
 */
export const SlotId = {
  // --- issue view: props { item, project } ---
  /** Buttons in the issue header, beside Star/Watch/Flag. */
  issueTitleAction: "issue.title.action",
  /** Rail cards above the fields. Order-sortable. */
  issuePanelSection: "issue.panel.section",
  /** Rail cards below the fields. */
  issueRailBottom: "issue.rail.bottom",
  /** Rail cards above the fields card, each drawing its own card. Order-sortable. */
  issueRailTop: "issue.rail.top",
  /** An Activity tab beside Comments/History/VCS: needs `title`; render is the tab body. */
  issueTab: "issue.tab",
  /** Beside a draft on the submission form. Props: `ItemDraftAssistProps`. Render nothing when
   *  there is nothing to suggest — the host hides the panel when every section is empty. */
  itemDraftAssist: "item.draft.assist",
  // --- the rich editor and rendered content ---
  /** A toolbar button. Props: `EditorToolbarActionProps`; draw it with `EditorToolbarButton`. */
  editorToolbarAction: "editor.toolbar.action",
  /** Chrome the host places over a selection. Props: `EditorSelectionActionProps` — `selection`
   *  is null while nothing is selected or focus left, so an open popover keeps its CAPTURED range. */
  editorSelectionAction: "editor.selection.action",
  /** An action on rendered content, for every reader. Props: `ReadActionProps`. */
  contentReadAction: "content.read.action",
  /** Draws a body a plugin claims; build with `contentBody(spec)`. Props: `ContentBodyProps`. */
  contentBody: "content.body",
  // --- views ---
  /** A view's header/toolbar. Props: { view, items } — the loaded, permission-scoped issues. */
  viewHeader: "view.header",
  /** A saved-view TYPE, `match` = the view_type key. Props: { view, items }. */
  viewType: "view.type",
  // --- settings ---
  /** A page under Settings, `match` = the pathname. Props: `ContributedPageProps`. */
  settingsPage: "settings.page",
  /** A page under a project's settings, `match` = the segment; pair it with a manifest
   *  `NavItemSpec(section="project_settings")`. Props: `ProjectSettingsPageProps`. */
  projectSettingsPage: "project.settings.page",
  /** A section inside an existing settings page, `match` = the page's slot key. */
  settingsSection: "settings.section",
  /** Settings footer. Props: { history: { entities?, projectId? } }. */
  settingsFooter: "settings.footer",
  /** Entity history. Props: { entityType, entityId, projectId?, title? }. */
  entityHistory: "entity.history",
  /** An owner's change line, `match` = the entity type. Props: { change }. */
  entityChangeLine: "entity.change.line",
  /** Datalist options from entity owners. Props: { entityType? }. */
  entityChangeFields: "entity.change.fields",
  /** A Profile section; mount `<UserContributionToggles>` here for per-user toggles. */
  profileSection: "profile.section",
  /** Under a plugin's row in Settings → Plugins, `match` = its name. Props: { plugin, pluginId };
   *  mount `<GlobalContributionToggles>` here for instance-wide toggles. */
  pluginManagerSection: "plugin.manager.section",
  // --- shell ---
  /** A folding sidebar section, `match` = the section key. Props: { collapsed, onToggle }. */
  sidebarSection: "sidebar.section",
  /** A page at a nav path; `match` is the path or a `$name` pattern (`matchPagePath`).
   *  Props: `ContributedPageProps`. */
  routePage: "route.page",
  /** A page outside the shell and the sign-in gate, `match` under `/public/`. The visitor may be
   *  anonymous: every request it makes must be one the server answers for a visitor. */
  publicPage: "public.page",
  /** A dashboard widget type. Props: { config, widget, filterQuery }. A manifest
   *  `WidgetTypeSpec(personal=True)` puts it on My Work instead of shared dashboards. */
  dashboardWidget: "dashboard.widget",
  /** A list column + board-card cell, `match` = the attribute id; build with `itemAttribute`. */
  itemAttribute: "item.attribute",
  /** A command-palette mode; build with `paletteMode(spec)`. */
  paletteMode: "palette.mode",
  /** A query-bar input mode (free text in, SLQ out); build with `queryInputMode(spec)`. */
  queryInputMode: "query.input.mode",
  /** One automation node type's inspector, `match` = the node type. Props:
   *  `AutomationNodeInspectorProps`; without one the host renders a form from the node's
   *  `params_schema`. */
  automationNodeInspector: "automation.node.inspector",
} as const;

export type SlotIdValue = (typeof SlotId)[keyof typeof SlotId];

/** A single contribution to a slot. `render` receives the slot's props. */
export interface SlotContribution<P = Record<string, unknown>> {
  /** Unique within the contributing plugin (dedupes re-registration). */
  id: string;
  /** Lower renders first (default 100). */
  order?: number;
  render: (props: P) => ReactNode;
  /** When set on a `route.page`/`settings.page`/`settings.section`, the host mounts this
   *  contribution only for the matching path/key. A PAGE's match may be a pattern whose `$name`
   *  segments capture (`matchPagePath`). Ignored for section-style slots. */
  match?: string;
  /** A label for tab/menu-style slots (e.g. `issue.tab` renders this as the tab button). */
  title?: ReactNode;
  /** An optional icon element for tab/menu-style slots. */
  icon?: ReactNode;
  /** A human-friendly name for this contribution in the per-contribution enable/disable UI
   *  (defaults to `id`). */
  label?: string;
  /** Whether this contribution is offered in the enable/disable toggle lists (default true). Set
   *  `false` for a plugin's own control surfaces (its `pluginManagerSection`/`profileSection`
   *  widgets) so they don't list — or hide — themselves. */
  toggleable?: boolean;
  /** What the anchor's host reads WITHOUT rendering — a column's label, widths and data source.
   *  Its shape belongs to the slot, and the SDK helper that builds the contribution writes it
   *  (`itemAttribute`). Readers validate it; a malformed one is skipped, never rendered. */
  meta?: Readonly<Record<string, unknown>>;
}

/** One row of a plugin's contribution list, for the enable/disable toggles UI. `enabled` reflects
 *  the requested scope (instance-wide for the admin list, per-user for the profile list). */
export interface ContributionInfo {
  slot: string;
  id: string;
  label: string;
  enabled: boolean;
}

/** Which set a toggle reads/writes: `global` = instance-wide (admin), `user` = this account only. */
export type ToggleScope = "global" | "user";

interface Entry {
  generation: number;
  plugin: string;
  slot: string;
  contribution: SlotContribution;
}

type Listener = () => void;

// Per-contribution disable sets (spec 94). Two orthogonal scopes, keyed `plugin::slot::id`:
//   • GLOBAL  — instance-wide, admin-owned (`/plugins/*/contribution-settings`). Off ⇒ hidden for
//               everyone AND not offered for per-user override.
//   • USER    — this account only (`/auth/me/preferences`). Only meaningful among globally-enabled
//               contributions.
// A contribution renders iff it's in NEITHER set. localStorage is a fast first-paint cache; the
// server is the source of truth (reconciled by `syncFromServer` once signed in).
const USER_STORAGE_KEY = "radd:disabled-contributions";
const GLOBAL_STORAGE_KEY = "radd:global-disabled-contributions";

function loadSet(storageKey: string): Set<string> {
  try {
    const raw = globalThis.localStorage?.getItem(storageKey);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function persistSet(storageKey: string, set: Set<string>): void {
  try {
    globalThis.localStorage?.setItem(storageKey, JSON.stringify([...set]));
  } catch {
    /* best-effort */
  }
}

class SlotRegistry {
  /** key `${slot}\u0000${plugin}\u0000${id}` → entry. */
  private entries = new Map<string, Entry>();
  private generation = 0;
  private listeners = new Set<Listener>();
  /** Per-slot snapshot cache so useSyncExternalStore sees a stable reference until a change. */
  private snapshots = new Map<string, Entry[]>();
  /** Contribution-list snapshot cache, keyed `${plugin}::${scope}` (for the toggles hooks). */
  private contribSnaps = new Map<string, ContributionInfo[]>();
  /** Instance-wide-disabled contributions (plugin::slot::id) — admin-owned. */
  private globalDisabled = loadSet(GLOBAL_STORAGE_KEY);
  /** This account's disabled contributions (plugin::slot::id). */
  private userDisabled = loadSet(USER_STORAGE_KEY);

  private dkey(plugin: string, slot: string, id: string): string {
    return `${plugin}::${slot}::${id}`;
  }

  /** Not disabled instance-wide. */
  isGloballyEnabled(plugin: string, slot: string, id: string): boolean {
    return !this.globalDisabled.has(this.dkey(plugin, slot, id));
  }

  /** Not disabled by this account. */
  isUserEnabled(plugin: string, slot: string, id: string): boolean {
    return !this.userDisabled.has(this.dkey(plugin, slot, id));
  }

  /** Visible = enabled in BOTH scopes. This is what `<Slot>` renders. */
  isVisible(plugin: string, slot: string, id: string): boolean {
    const k = this.dkey(plugin, slot, id);
    return !this.globalDisabled.has(k) && !this.userDisabled.has(k);
  }

  /** Drop the snapshots a change can reach and notify. `membership`: which plugins hold entries changed. */
  private changed(slots: Iterable<string> | "all", membership = false): void {
    if (slots === "all") this.snapshots.clear();
    else for (const slot of slots) this.snapshots.delete(slot);
    this.contribSnaps.clear();
    if (membership) this.activeSnap = null;
    this.navSnap = null;
    this.disabledMatchSnaps.clear();
    this.emit();
  }

  // --- per-user scope (persists to /auth/me/preferences) ---
  setUserEnabled(plugin: string, slot: string, id: string, enabled: boolean): void {
    const k = this.dkey(plugin, slot, id);
    if (enabled) this.userDisabled.delete(k);
    else this.userDisabled.add(k);
    persistSet(USER_STORAGE_KEY, this.userDisabled);
    this.saveUserToServer();
    this.changed([slot]);
  }

  private userTimer: ReturnType<typeof setTimeout> | undefined;

  private saveUserToServer(): void {
    if (this.userTimer) clearTimeout(this.userTimer);
    this.userTimer = setTimeout(() => {
      void api
        .put("/auth/me/preferences", { [PREF_KEY]: [...this.userDisabled] }, { throwOn401: true })
        .catch(() => {
          /* offline / not signed in — localStorage still holds it */
        });
    }, 400);
  }

  // --- instance-wide scope (persists to /plugins/{id}/contribution-settings, admin only) ---
  /** `pluginId` is the pluginmgr id (dotted) the endpoint keys on; `plugin` is the registry name. */
  setGlobalEnabled(
    plugin: string,
    pluginId: string,
    slot: string,
    id: string,
    enabled: boolean,
  ): void {
    const k = this.dkey(plugin, slot, id);
    if (enabled) this.globalDisabled.delete(k);
    else this.globalDisabled.add(k);
    persistSet(GLOBAL_STORAGE_KEY, this.globalDisabled);
    this.saveGlobalToServer(plugin, pluginId);
    this.changed([slot]);
  }

  /** name → pluginmgr id for plugins with a pending global save. */
  private globalPending = new Map<string, string>();
  private globalTimer: ReturnType<typeof setTimeout> | undefined;

  private saveGlobalToServer(plugin: string, pluginId: string): void {
    this.globalPending.set(plugin, pluginId);
    if (this.globalTimer) clearTimeout(this.globalTimer);
    this.globalTimer = setTimeout(() => {
      const pending = [...this.globalPending.entries()];
      this.globalPending.clear();
      for (const [name, id] of pending) {
        // The plugin's own disabled keys, stored server-side as `<slot>::<id>` (plugin-scoped).
        const prefix = `${name}::`;
        const disabled = [...this.globalDisabled]
          .filter((key) => key.startsWith(prefix))
          .map((key) => key.slice(prefix.length));
        void api
          .put(`/plugins/${id}/contribution-settings`, { disabled }, { throwOn401: true })
          .catch(() => {
            /* not an admin / offline — localStorage still reflects the intent locally */
          });
      }
    }, 400);
  }

  /** Load BOTH disabled sets from the server (source of truth) and reconcile. Called by the host
   *  once the user is authenticated, so global availability + per-user toggles are correct. */
  async syncFromServer(): Promise<void> {
    let changed = false;
    try {
      const prefs = await api.get<Record<string, unknown>>("/auth/me/preferences", {
        throwOn401: true,
      });
      const keys = prefs[PREF_KEY];
      if (Array.isArray(keys)) {
        this.userDisabled = new Set(keys.map(String));
        persistSet(USER_STORAGE_KEY, this.userDisabled);
        changed = true;
      }
    } catch {
      /* not signed in / offline — keep the localStorage set */
    }
    try {
      const g = await api.get<{ disabled?: unknown }>("/plugins/contribution-settings", {
        throwOn401: true,
      });
      if (Array.isArray(g.disabled)) {
        this.globalDisabled = new Set(g.disabled.map(String));
        persistSet(GLOBAL_STORAGE_KEY, this.globalDisabled);
        changed = true;
      }
    } catch {
      /* endpoint unreachable — keep the localStorage set */
    }
    if (changed) this.changed("all");
  }

  /** A plugin's TOGGLEABLE contributions with their enabled state for `scope`. The `user` scope
   *  lists only globally-enabled ones (a globally-off piece is never offered for per-user override). */
  contributionsOf(plugin: string, scope: ToggleScope): ContributionInfo[] {
    const cacheKey = `${plugin}::${scope}`;
    const cached = this.contribSnaps.get(cacheKey);
    if (cached) return cached;
    const list = [...this.entries.values()]
      .filter((e) => e.plugin === plugin && e.contribution.toggleable !== false)
      .filter((e) => scope === "global" || this.isGloballyEnabled(plugin, e.slot, e.contribution.id))
      .map((e) => ({
        slot: e.slot,
        id: e.contribution.id,
        label: e.contribution.label ?? e.contribution.id,
        enabled:
          scope === "global"
            ? this.isGloballyEnabled(plugin, e.slot, e.contribution.id)
            : this.isUserEnabled(plugin, e.slot, e.contribution.id),
      }));
    this.contribSnaps.set(cacheKey, list);
    return list;
  }

  private key(slot: string, plugin: string, id: string): string {
    return `${slot}\u0000${plugin}\u0000${id}`;
  }

  register(slot: string, contribution: SlotContribution, plugin: string): void {
    this.entries.set(this.key(slot, plugin, contribution.id), { plugin, slot, contribution, generation: ++this.generation });
    this.changed([slot], true);
  }

  unregister(slot: string, plugin: string, id: string): void {
    if (this.entries.delete(this.key(slot, plugin, id))) this.changed([slot], true);
  }

  /** Remove every contribution a plugin made — the runtime-disable path. */
  unregisterPlugin(plugin: string): void {
    const touched = new Set<string>();
    for (const [key, entry] of this.entries) {
      if (entry.plugin === plugin) {
        this.entries.delete(key);
        touched.add(entry.slot);
      }
    }
    if (touched.size) this.changed(touched, true);
  }

  private activeSnap: string[] | null = null;
  private navSnap: string[] | null = null;
  private disabledMatchSnaps = new Map<string, string[]>();

  /** The `match` values registered for `slot` whose contribution is currently hidden (disabled in
   *  either scope). Any host UI that enumerates keyed options from the BACKEND manifest — the view-
   *  type / widget-type dropdowns, nav links — filters by this so a turned-off contribution's option
   *  disappears. A match with no registered contribution is absent here (the manifest still governs
   *  it; the remote may simply not have loaded). Cached per slot for a stable snapshot. */
  disabledMatches(slot: string): string[] {
    const cached = this.disabledMatchSnaps.get(slot);
    if (cached) return cached;
    const out: string[] = [];
    for (const e of this.entries.values()) {
      if (
        e.slot === slot &&
        typeof e.contribution.match === "string" &&
        !this.isVisible(e.plugin, e.slot, e.contribution.id)
      ) {
        out.push(e.contribution.match);
      }
    }
    this.disabledMatchSnaps.set(slot, out);
    return out;
  }

  /** Nav paths (`route.page` + `settings.page` matches) that are turned off — a stable union used
   *  by both sidebars and the page hosts. Cached for a stable useSyncExternalStore snapshot. */
  disabledNavPaths(): string[] {
    if (this.navSnap) return this.navSnap;
    this.navSnap = [
      ...this.disabledMatches(SlotId.routePage),
      ...this.disabledMatches(SlotId.settingsPage),
    ];
    return this.navSnap;
  }

  /** The plugins that currently have at least one contribution registered (cached for a stable
   *  useSyncExternalStore snapshot). */
  activePlugins(): string[] {
    if (this.activeSnap) return this.activeSnap;
    const set = new Set<string>();
    for (const entry of this.entries.values()) set.add(entry.plugin);
    this.activeSnap = [...set];
    return this.activeSnap;
  }

  forSlot(slot: string): Entry[] {
    const cached = this.snapshots.get(slot);
    if (cached) return cached;
    const list = [...this.entries.values()]
      .filter((e) => e.slot === slot && this.isVisible(e.plugin, slot, e.contribution.id))
      .sort((a, b) => (a.contribution.order ?? 100) - (b.contribution.order ?? 100));
    this.snapshots.set(slot, list);
    return list;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }
}

/** One registry, kept on `globalThis` so even an accidental second copy of this module shares it. */
const GLOBAL_KEY = "__RADD_SLOT_REGISTRY__";
type GlobalWithRegistry = typeof globalThis & { [GLOBAL_KEY]?: SlotRegistry };
const g = globalThis as GlobalWithRegistry;
const registry: SlotRegistry = g[GLOBAL_KEY] ?? (g[GLOBAL_KEY] = new SlotRegistry());

/** Register a slot contribution. `plugin` tags it so disable can remove it wholesale. */
export function registerSlot(
  slot: SlotIdValue | string,
  contribution: SlotContribution,
  opts: { plugin: string },
): void {
  registry.register(slot, contribution, opts.plugin);
}

/** Remove a single contribution. */
export function unregisterSlot(slot: string, plugin: string, id: string): void {
  registry.unregister(slot, plugin, id);
}

/** Remove every contribution a plugin registered (runtime disable / remote unload). */
export function unregisterPlugin(plugin: string): void {
  registry.unregisterPlugin(plugin);
}

/** The plugins with at least one live contribution (diagnostics / the plugins admin). */
export function activeSlotPlugins(): string[] {
  return registry.activePlugins();
}

/** Reactive: the plugin names that currently have UI contributions loaded. */
export function useActiveSlotPlugins(): string[] {
  return useSyncExternalStore(
    (l) => registry.subscribe(l),
    () => registry.activePlugins(),
    () => registry.activePlugins(),
  );
}

/** Reactive: nav paths whose `route.page`/`settings.page` contribution is loaded but turned off
 *  (per-user or instance-wide). The host filters manifest nav links by this, and the page hosts use
 *  it to show a "turned off" notice instead of an endless spinner. */
export function useDisabledNavPaths(): Set<string> {
  const paths = useSyncExternalStore(
    (l) => registry.subscribe(l),
    () => registry.disabledNavPaths(),
    () => registry.disabledNavPaths(),
  );
  return useMemo(() => new Set(paths), [paths]);
}

/** Reactive: the `match` keys registered for `slot` that are currently turned off (either scope).
 *  A host UI that lists keyed options from the backend manifest — the view-type / widget-type
 *  dropdowns — filters them out with this, so a disabled type stops being offered. */
export function useDisabledMatches(slot: SlotIdValue | string): Set<string> {
  const keys = useSyncExternalStore(
    (l) => registry.subscribe(l),
    () => registry.disabledMatches(slot),
    () => registry.disabledMatches(slot),
  );
  return useMemo(() => new Set(keys), [keys]);
}

/** Load BOTH contribution-scope prefs from the server (source of truth). The host calls this once
 *  the user is authenticated, so instance-wide availability + per-user toggles are correct and
 *  follow the user across browsers. */
export function syncContributionPrefs(): Promise<void> {
  return registry.syncFromServer();
}

/** Turn a contribution on/off for THIS account (Profile scope; persisted, live). */
export function setUserContributionEnabled(
  plugin: string,
  slot: string,
  id: string,
  enabled: boolean,
): void {
  registry.setUserEnabled(plugin, slot, id, enabled);
}

/** Turn a contribution on/off INSTANCE-WIDE (admin scope; persisted, live). `pluginId` is the
 *  pluginmgr id the `/plugins/{id}/contribution-settings` endpoint keys on. */
export function setGlobalContributionEnabled(
  plugin: string,
  pluginId: string,
  slot: string,
  id: string,
  enabled: boolean,
): void {
  registry.setGlobalEnabled(plugin, pluginId, slot, id, enabled);
}

function useContributions(plugin: string, scope: ToggleScope): ContributionInfo[] {
  return useSyncExternalStore(
    (l) => registry.subscribe(l),
    () => registry.contributionsOf(plugin, scope),
    () => registry.contributionsOf(plugin, scope),
  );
}

/** A plugin's toggleable contributions + a live setter for the PER-USER scope (Profile page). Lists
 *  only contributions that are enabled instance-wide. */
export function useUserContributionToggles(plugin: string): {
  contributions: ContributionInfo[];
  setEnabled: (slot: string, id: string, enabled: boolean) => void;
} {
  const contributions = useContributions(plugin, "user");
  return {
    contributions,
    setEnabled: (slot, id, enabled) => registry.setUserEnabled(plugin, slot, id, enabled),
  };
}

/** A plugin's toggleable contributions + a live setter for the INSTANCE-WIDE scope (Settings →
 *  Plugins, admin). `pluginId` is the pluginmgr id. */
export function useGlobalContributionToggles(
  plugin: string,
  pluginId: string,
): {
  contributions: ContributionInfo[];
  setEnabled: (slot: string, id: string, enabled: boolean) => void;
} {
  const contributions = useContributions(plugin, "global");
  return {
    contributions,
    setEnabled: (slot, id, enabled) =>
      registry.setGlobalEnabled(plugin, pluginId, slot, id, enabled),
  };
}

function ToggleList({
  items,
  onSet,
  empty,
}: {
  items: ContributionInfo[];
  onSet: (slot: string, id: string, enabled: boolean) => void;
  empty: string;
}): ReactNode {
  if (items.length === 0) return <p className="text-[13px] text-fg-faint">{empty}</p>;
  return (
    <ul className="flex flex-col gap-2">
      {items.map((c) => (
        <li key={`${c.slot}:${c.id}`} className="flex items-center justify-between gap-4">
          <span className="text-[13px] text-fg">
            {c.label}
            <span className="ml-1.5 text-[11px] text-fg-faint">({c.slot})</span>
          </span>
          <Switch checked={c.enabled} label={c.label} hideLabel onChange={(on) => onSet(c.slot, c.id, on)} />
        </li>
      ))}
    </ul>
  );
}

/** Ready-made INSTANCE-WIDE contribution toggles (admin) — a switch per contribution. A plugin
 *  drops this into a `pluginManagerSection` slot; Off ⇒ the piece is hidden for everyone and won't
 *  appear on anyone's Profile. Opt-in: a plugin that never mounts it has no admin toggles. */
export function GlobalContributionToggles({
  plugin,
  pluginId,
}: {
  plugin: string;
  pluginId: string;
}): ReactNode {
  const { contributions, setEnabled } = useGlobalContributionToggles(plugin, pluginId);
  return (
    <ToggleList
      items={contributions}
      onSet={setEnabled}
      empty="This plugin exposes no toggleable UI components."
    />
  );
}

/** Ready-made PER-USER contribution toggles (Profile) — a switch per contribution. A plugin
 *  drops this into a `profileSection` slot; it lists only contributions enabled instance-wide. */
export function UserContributionToggles({ plugin }: { plugin: string }): ReactNode {
  const { contributions, setEnabled } = useUserContributionToggles(plugin);
  return (
    <ToggleList
      items={contributions}
      onSet={setEnabled}
      empty="This plugin has no components you can turn on or off."
    />
  );
}

/** A keyed contribution whose `meta` is `spec` without its `render`: id `<kind>:<spec.id>`, match
 *  `spec.id`. The anchor's host reads the meta without rendering. */
export function metaContribution<P>(slot: string, kind: string, spec: { id: string; render: (props: P) => ReactNode },
  label: string): PluginContribution {
  const { render, ...meta } = spec;
  return { id: `${kind}:${spec.id}`, slot, match: spec.id, label, meta, render: (props) => render(props as unknown as P) };
}

/** A keyed contribution's `meta.id` when it is its `match` and inside its owner's `<plugin>.`
 *  namespace, else null: a foreign id would let one plugin shadow another's. */
export function ownedMetaId(plugin: string, match: string | undefined, meta: Readonly<Record<string, unknown>> | undefined): string | null {
  if (!meta || typeof meta.id !== "string" || meta.id !== match) return null;
  const prefix = `${plugin}.`;
  return meta.id.startsWith(prefix) && meta.id.length > prefix.length ? meta.id : null;
}

/** Live-subscribing hook: the contributions registered for `slot`, re-rendering on change. */
export function useSlot(slot: SlotIdValue | string): Entry[] {
  return useSyncExternalStore(
    (l) => registry.subscribe(l),
    () => registry.forSlot(slot),
    () => registry.forSlot(slot),
  );
}

class SlotErrorBoundary extends Component<
  { plugin: string; children: ReactNode; fallback?: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    // Quarantine at the render layer: a plugin section that throws is hidden, not fatal.
    console.error(`[radd-plugin-sdk] slot contribution from "${this.props.plugin}" crashed`, error, info);
  }
  render() {
    if (this.state.failed) return this.props.fallback ?? null;
    return this.props.children;
  }
}

/** Which plugin's contribution this subtree is — so a host surface a contribution OPENS (a reading
 *  panel) can be withdrawn with the plugin that opened it (RADD-1395). */
const ContributionOwnerContext = createContext<string | null>(null);

/** The plugin whose slot contribution renders the calling component; null outside one. */
export function useContributionOwner(): string | null {
  return useContext(ContributionOwnerContext);
}

/** A plugin's rendered output placed OUTSIDE a `<Slot>` (a live session's chrome, RADD-1397): the
 *  same quarantine and the same owner context a slot contribution gets. SDK-internal. */
export function ContributionFrame({ plugin, children }: { plugin: string; children: ReactNode }) {
  return (
    <SlotErrorBoundary plugin={plugin}>
      <ContributionOwnerContext.Provider value={plugin}>{children}</ContributionOwnerContext.Provider>
    </SlotErrorBoundary>
  );
}

function Contribution({ entry, props }: { entry: Entry; props: Record<string, unknown> }) {
  return (
    <ContributionOwnerContext.Provider value={entry.plugin}>
      {entry.contribution.render(props)}
    </ContributionOwnerContext.Provider>
  );
}

/**
 * Render every plugin contribution for a slot. Each is isolated in an error boundary, so one bad
 * plugin section never takes down the host view. All extra props are forwarded to each `render`.
 */
export function Slot({
  id,
  match,
  owner,
  fallback = null,
  pending = null,
  errorFallback = null,
  ...props
}: {
  id: SlotIdValue | string;
  /** When set, only contributions whose `match` equals this render — for keyed slots like
   *  `view.type`/`settings.page` where exactly one plugin owns a value. */
  match?: string;
  /** When set, only this plugin's contributions render — for a keyed slot whose key names its
   *  owner (`item.attribute`), so another plugin registering the same key cannot draw into it. */
  owner?: string;
  /** Rendered when nothing contributes and no plugin bundle is still loading. */
  fallback?: ReactNode;
  /** Rendered when nothing contributes YET: a plugin bundle is still loading (RADD-1373). */
  pending?: ReactNode;
  errorFallback?: ReactNode;
} & Record<string, unknown>): ReactNode {
  const all = useSlot(id);
  const loading = useRemotesLoading();
  const entries = all.filter((e) =>
    (match === undefined || e.contribution.match === match) && (owner === undefined || e.plugin === owner));
  if (entries.length === 0) return loading ? pending : fallback;
  return entries.map((entry) => (
    <SlotErrorBoundary key={`${entry.plugin}:${entry.contribution.id}:${entry.generation}`} plugin={entry.plugin} fallback={errorFallback}>
      <Contribution entry={entry} props={props} />
    </SlotErrorBoundary>
  ));
}

/** The first contribution whose `match` equals `matchValue`, for a keyed slot one page owns. */
export function useSlotMatch(
  slot: SlotIdValue | string,
  matchValue: string,
): Entry | undefined {
  const entries = useSlot(slot);
  return entries.find((e) => e.contribution.match === matchValue);
}
