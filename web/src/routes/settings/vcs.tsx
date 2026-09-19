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
import { EmptyState } from "../../components/EmptyState";
import { RoutePath } from "../../lib/constants";
import { capabilitiesQuery } from "../../lib/queries";

/**
 * Settings → Version control (RADD-1262): ONE page for every host kind, a tab
 * each — the way Import data holds Jira and Confluence — instead of a nav entry
 * per kind. The tab is URL-carried (`?host=gitlab`) so a link lands on the right
 * host, and the old per-kind paths redirect here.
 *
 * A kind whose plugin is disabled keeps its tab and explains itself; hiding it
 * would make "where did GitLab go" a support question.
 */
export function VcsSettingsPage() {
  const search = useSearch({ strict: false }) as { host?: VcsHostKindValue };
  const navigate = useNavigate();
  const manifest = useQuery(capabilitiesQuery);
  const mounted = new Set(manifest.data?.plugins ?? []);
  const active: VcsHostKindValue = isVcsHostKind(search.host) ? search.host : VCS_HOST_KINDS[0];
  const config = VCS_HOST_CONFIGS[active];
  const select = (host: VcsHostKindValue) =>
    void navigate({ to: RoutePath.settingsVcs, search: { host }, replace: true });

  return (
    <SettingsPage
      title="Version control"
      description="Hosts whose branches, commits, merge and pull requests link themselves to issues by key, ship work through releases, and mirror the time logged on them."
      history={{ entities: config.historyEntities }}
    >
      <div role="tablist" aria-label="Version control hosts" className="mb-5 flex flex-wrap gap-1 border-b border-subtle">
        {VCS_HOST_KINDS.map((kind) => {
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
              {manifest.data && !mounted.has(kind) && (
                <span className="rounded bg-elevated px-1.5 py-px text-[10px] text-fg-muted">off</span>
              )}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" id={`vcs-panel-${active}`} aria-labelledby={`vcs-tab-${active}`}>
        {manifest.data && !mounted.has(active) ? (
          <EmptyState
            icon={GitBranch}
            message={`The ${config.title} connector is disabled, so its hosts cannot be configured here.`}
            action={
              <Link to={RoutePath.settingsPlugins} className="text-sm text-accent-text hover:underline">
                Enable it in Plugins →
              </Link>
            }
          />
        ) : (
          <VcsHostSettings key={active} config={config} />
        )}
      </div>
    </SettingsPage>
  );
}
