import { useEffect } from "react";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { GitBranch } from "lucide-react";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { VcsHostSettings } from "../../components/settings/VcsHostSettings";
import {
  VCS_HOST_CONFIGS,
  VCS_HOST_KINDS,
  isVcsHostKind,
  type VcsHostKindValue,
} from "../../components/settings/vcs-hosts";
import { Spinner } from "../../components/Spinner";
import { QueryError } from "../../components/QueryError";
import { EmptyState } from "../../components/EmptyState";
import { RoutePath } from "../../lib/constants";
import { capabilitiesQuery } from "../../lib/queries";

/**
 * Settings → Version control (RADD-1262): ONE page for every host kind, a tab
 * each — the way Import data holds Jira and Confluence — instead of a nav entry
 * per kind. The tab is URL-carried (`?host=gitlab`) so a link lands on the right
 * host, and the old per-kind paths redirect here.
 *
 * Only loaded connectors appear. Old links fall back to an available provider;
 * plugin discovery and enabling belong on the Plugins page.
 */
export function VcsSettingsPage() {
  const search = useSearch({ strict: false }) as { host?: VcsHostKindValue };
  const navigate = useNavigate();
  const manifest = useQuery(capabilitiesQuery);
  const mounted = new Set(manifest.data?.plugins ?? []);
  const available = VCS_HOST_KINDS.filter(kind => mounted.has(kind));
  const active = isVcsHostKind(search.host) && mounted.has(search.host) ? search.host : available[0];
  const config = active ? VCS_HOST_CONFIGS[active] : undefined;
  useEffect(() => {
    if (manifest.data && active && search.host !== active) {
      void navigate({ to: RoutePath.settingsVcs, search: { host: active }, replace: true });
    }
  }, [manifest.data, active, search.host, navigate]);
  const select = (host: VcsHostKindValue) =>
    void navigate({ to: RoutePath.settingsVcs, search: { host }, replace: true });

  return (
    <SettingsPage
      title="Version control"
      description="Hosts whose branches, commits, merge and pull requests link themselves to issues by key, and — per repository, when switched on — copy the time logged on them. Merges, pushes, CI results and releases are automation triggers."
      history={config ? { entities: config.historyEntities } : undefined}
    >
      {manifest.isPending ? <Spinner /> : manifest.isError ? <QueryError label="connectors" error={manifest.error} /> : !config ? (
        <EmptyState icon={GitBranch} message="No version control connectors are enabled." action={
          <Link to={RoutePath.settingsPlugins} className="text-sm text-accent-text hover:underline">Manage plugins →</Link>
        } />
      ) : <>
      <div role="tablist" aria-label="Version control hosts" className="mb-5 flex flex-wrap gap-1 border-b border-subtle">
        {available.map((kind) => {
          const isActive = kind === active;
          return (
            <button
              key={kind}
              type="button"
              role="tab"
              id={`vcs-tab-${kind}`}
              aria-selected={isActive}
              aria-controls={`vcs-panel-${kind}`}
              onClick={() => select(kind)}
              className={
                "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-[13px] cursor-pointer focus-visible:outline-2 focus-visible:outline-focus " +
                (isActive ? "border-accent-hover text-heading" : "border-transparent text-fg-muted hover:text-fg")
              }
            >
              <GitBranch size={13} aria-hidden />
              {VCS_HOST_CONFIGS[kind].title}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" id={`vcs-panel-${active}`} aria-labelledby={`vcs-tab-${active}`}>
        <VcsHostSettings key={active} config={config} />
      </div>
      </>}
    </SettingsPage>
  );
}
