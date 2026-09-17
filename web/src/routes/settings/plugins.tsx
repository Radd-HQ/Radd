import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Slot, SlotId, useSlotMatch } from "@radd/plugin-sdk";
import { Blocks, ChevronDown, ChevronRight, Lock, SlidersHorizontal } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { pluginsQuery, queryKeys } from "../../lib/queries";
import { type Plugin } from "../../lib/types";
import { Button } from "../../components/Button";
import { useConfirm } from "../../components/ConfirmDialog";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { TextField } from "../../components/TextField";
import { Spinner } from "../../components/Spinner";
import { QueryError } from "../../components/QueryError";
import { settingsPathForPlugin } from "./layout";

const STATE_STYLES: Record<string, string> = {
  enabled: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  installed: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  disabled: "bg-emphasis/20 text-fg-secondary ring-emphasis/30",
  discovered: "bg-emphasis/20 text-fg-secondary ring-emphasis/30",
  errored: "bg-red-500/15 text-red-300 ring-red-500/30",
};

function StateBadge({ state }: { state: string }) {
  const cls = STATE_STYLES[state] ?? STATE_STYLES.discovered;
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ring-1 ${cls}`}>
      {state}
    </span>
  );
}

function PluginRow({ plugin }: { plugin: Plugin }) {
  const queryClient = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.plugins });
    // The nav/capabilities manifest reflects enabled plugins — refresh it so the
    // sidebar plugin nav appears/disappears immediately.
    queryClient.invalidateQueries({ queryKey: ["capabilities"] });
  };
  // RADD-1101: install/uninstall always existed as endpoints; the page offered
  // only enable/disable, leaving the lifecycle's ends to curl.
  const install = useMutation({
    mutationFn: () => api.post<Plugin[]>(`${ApiPath.plugins}/${plugin.id}/install`),
    onSuccess: invalidate,
  });
  const uninstall = useMutation({
    mutationFn: () => api.post<Plugin[]>(`${ApiPath.plugins}/${plugin.id}/uninstall`),
    onSuccess: invalidate,
  });
  const enable = useMutation({
    mutationFn: () => api.post<Plugin[]>(`${ApiPath.plugins}/${plugin.id}/enable`),
    onSuccess: invalidate,
  });
  const disable = useMutation({
    mutationFn: () => api.post<Plugin[]>(`${ApiPath.plugins}/${plugin.id}/disable`),
    onSuccess: invalidate,
  });
  const busy = enable.isPending || disable.isPending || install.isPending || uninstall.isPending;
  const actionError = enable.error || disable.error || install.error || uninstall.error;
  const enabled = plugin.state === "enabled";
  // A plugin OPTS IN to instance-wide contribution toggles (spec 94) by contributing a
  // `pluginManagerSection` widget keyed by its registry name — the kernel forces nothing. If it did,
  // the row gets an expander revealing that plugin-owned admin UI (its GlobalContributionToggles).
  const adminSection = useSlotMatch(SlotId.pluginManagerSection, plugin.name);
  const settingsLink = settingsPathForPlugin(plugin.name);
  const hasSection = adminSection !== undefined;
  const [open, setOpen] = useState(false);

  return (
    <li className="border-b border-subtle/60 last:border-b-0">
      <div className="flex items-center gap-3 px-4 py-3">
        {hasSection ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-label={`${open ? "Hide" : "Show"} ${plugin.id} components`}
            className="shrink-0 rounded p-0.5 text-fg-muted hover:bg-elevated hover:text-fg"
          >
            {open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
          </button>
        ) : (
          <Blocks size={16} className="shrink-0 text-accent-text" aria-hidden />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-[13px] font-medium text-heading">{plugin.id}</span>
            <span className="text-[11px] text-fg-muted">v{plugin.version}</span>
            <StateBadge state={plugin.state} />
            <span className="text-[11px] text-fg-muted">{plugin.origin === "package" ? "Package" : "Built in"}</span>
            {/* Connector configured-ness (env token present) — the home for
                per-connector status since the 2026-08-01 reorg; the Server
                Overview keeps only a summary count. */}
            {plugin.capabilities
              .filter((cap) => cap.category === "connector")
              .map((cap) => (
                <span
                  key={cap.key}
                  className={`rounded-full px-1.5 py-px text-[10px] font-medium ring-1 ${
                    cap.enabled
                      ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30"
                      : "bg-emphasis/20 text-fg-secondary ring-emphasis/30"
                  }`}
                  title={
                    cap.enabled
                      ? `${cap.label}: environment configuration present`
                      : `${cap.label}: not configured (set its environment variables)`
                  }
                >
                  {cap.enabled ? "Configured" : "Not configured"}
                </span>
              ))}
          </div>
          {plugin.description && (
            <p className="mt-0.5 truncate text-[12px] text-fg-muted">{plugin.description}</p>
          )}
          <p className="mt-1 text-[12px] text-fg-muted">
            {plugin.active ? "Loaded on this server" : "Not loaded on this server"}
            {plugin.restart_required && " · Restart required to apply this change"}
          </p>
          {plugin.dependencies?.length > 0 && <p className="mt-1 text-[12px] text-fg-muted">
            Requires: {plugin.dependencies.join(", ")}
          </p>}
          {plugin.problems?.map((problem) => <p key={problem} className="mt-1 text-[12px] text-fg">{problem}</p>)}
          {actionError && <p role="alert" className="mt-1 text-[12px] text-fg">{actionError.message}</p>}
        </div>
        {/* RADD-928: a plugin that owns a settings tab links to it from here, so
            "where do I configure this?" is answered on the plugin's own row —
            the discoverability a dedicated tab otherwise costs. Only while
            enabled: the tab is withdrawn with the plugin. */}
        {plugin.active && settingsLink && (
          <Link
            to={settingsLink.to}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-accent-text hover:bg-elevated hover:text-accent-text-strong focus-visible:outline-2 focus-visible:outline-focus"
          >
            <SlidersHorizontal size={12} aria-hidden />
            {settingsLink.label}
          </Link>
        )}
        {plugin.core ? (
          <span className="flex items-center gap-1 text-[12px] text-fg-muted">
            <Lock size={12} aria-hidden /> Core
          </span>
        ) : !plugin.can_toggle ? (
          <span className="text-[12px] text-fg-muted">Package needs attention</span>
        ) : plugin.state === "discovered" ? (
          <Button size="sm" disabled={busy} onClick={() => install.mutate()}>
            {install.isPending ? "Installing…" : "Install"}
          </Button>
        ) : enabled ? (
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => disable.mutate()}>
            Disable
          </Button>
        ) : (
          <>
            <Button size="sm" disabled={busy || (plugin.problems?.length ?? 0) > 0} onClick={() => enable.mutate()}>
              Enable
            </Button>
            {plugin.origin === "package" && <Button
              size="sm"
              variant="ghost"
              className="border border-strong hover:border-red-500/50 hover:text-red-300"
              disabled={busy || plugin.active}
              onClick={() => {
                void confirm({
                  title: `Forget ${plugin.id}?`,
                  message:
                    "This removes registration and plugin-specific permission grants. Stored plugin data and the deployed package remain. Reinstalling will require reviewing permissions again.",
                  confirmLabel: "Forget plugin",
                  danger: true,
                }).then((ok) => {
                  if (ok) uninstall.mutate();
                });
              }}
            >
              {uninstall.isPending ? "Forgetting…" : "Forget…"}
            </Button>}
          </>
        )}
      </div>
      {confirmDialog}
      {open && hasSection && (
        <div className="border-t border-subtle/40 bg-base/30 px-4 py-3 pl-11">
          <p className="mb-2 text-[11px] text-fg-muted">
            Availability of this plugin's UI components — applies to <strong>everyone</strong>. Off
            here also removes it from the per-user controls on Profile.
          </p>
          {/* Plugin-owned admin UI: the plugin renders its own toggles (e.g. GlobalContributionToggles). */}
          <Slot
            id={SlotId.pluginManagerSection}
            match={plugin.name}
            plugin={plugin.name}
            pluginId={plugin.id}
          />
        </div>
      )}
    </li>
  );
}

export function PluginsSettingsPage() {
  const { data: plugins, isLoading, error } = useQuery(pluginsQuery);
  const [search, setSearch] = useState("");
  const visible = (plugins ?? []).filter(plugin =>
    `${plugin.id} ${plugin.name} ${plugin.description}`.toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <SettingsPage history={{ entities: ["plugin"] }}
      title="Plugins"
      description="Manage plugin packages delivered with your deployment. Enable and disable save the requested state; restart all web and worker processes to apply it."
    >
      <div className="mb-4 rounded-lg border border-subtle bg-surface p-4 text-[13px] text-fg-secondary">
        <p className="font-medium text-heading">Add a plugin</p>
        <p className="mt-1">Deploy an image containing the versioned plugin package to both web and workers.
          It appears here automatically. Install it, review its requirements, enable it, then restart all processes.</p>
        <p className="mt-2">Updates use a new deployment image. Disabling keeps data; forgetting also removes plugin-specific grants.
          The loaded status below describes this server only.</p>
      </div>
      <div className="mb-4">
        <TextField label="Find a plugin" placeholder="Search by name or description…"
          value={search} onChange={event => setSearch(event.target.value)} />
      </div>
      {isLoading ? (
        <Spinner />
      ) : error ? (
        <QueryError label="plugins" error={error} />
      ) : (
        <ul className="overflow-hidden rounded-lg border border-subtle/80 bg-surface/40">
          {visible.length === 0 && <li className="px-4 py-3 text-[13px] text-fg-muted">No plugins match your search.</li>}
          {visible.map((p) => (
            <PluginRow key={p.id} plugin={p} />
          ))}
        </ul>
      )}
    </SettingsPage>
  );
}
