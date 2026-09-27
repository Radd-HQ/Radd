import type { ReactNode } from "react";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { GitBranch } from "lucide-react";
import { EmptyState, QueryError, SettingsPage, Slot, SlotId, Spinner, usePermissions } from "@radd/plugin-sdk";
import { historyEntities, useConnectors } from "./queries";
import type { VcsConnector } from "./types";
import { VcsHostSettings } from "./VcsHostSettings";

const NO_PERMISSION = "You do not have permission to manage version control connections.";

/** Settings → Version control: one tab per connector plugin loaded now. The wording
 * is each connector's (declared on its manifest); the page and every tab are vcs's. */
export function VcsSettingsPage() {
  const search = useSearch({ strict: false }) as { host?: string };
  const navigate = useNavigate();
  const allowed = usePermissions().global("global.manage");
  const connectors = useConnectors(allowed);
  const list = connectors.data ?? [];
  const requestedMissing = Boolean(search.host) && !list.some((connector) => connector.provider === search.host);
  const active = list.find((connector) => connector.provider === search.host) ?? list[0];
  const select = (host: string) =>
    void navigate({ to: "/settings/$", params: { _splat: "vcs" }, search: { host }, replace: true });

  let body: ReactNode;
  if (connectors.data === undefined && !allowed) {
    body = <p role="alert" className="text-sm text-fg-muted">{NO_PERMISSION}</p>;
  } else if (connectors.isError) {
    body = <QueryError label="version control connectors" error={connectors.error} />;
  } else if (connectors.data === undefined || (connectors.settling && (list.length === 0 || requestedMissing))) {
    // A connector just enabled may still be on its way: wait rather than claim
    // there are none, or that the requested one is unavailable.
    body = <div role="status" className="flex items-center gap-2 text-sm text-fg-muted"><Spinner />Loading connectors…</div>;
  } else if (!active) {
    body = <EmptyState icon={GitBranch} message="No version control connectors are available."
      action={<Link to="/settings/plugins" className="text-accent-text hover:underline">Manage plugins →</Link>} />;
  } else {
    body = <>
      {requestedMissing && <p className="mb-3 text-sm text-fg-muted">The requested connector is unavailable. Showing {active.title}.</p>}
      <div role="tablist" aria-label="Version control hosts" className="mb-5 flex flex-wrap gap-1 border-b border-subtle">
        {list.map((connector) => <button key={connector.provider} type="button" role="tab"
          id={`vcs-tab-${connector.provider}`} aria-controls={`vcs-panel-${connector.provider}`} aria-selected={connector === active}
          onClick={() => select(connector.provider)}
          className={"-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-[13px] cursor-pointer focus-visible:outline-2 focus-visible:outline-focus " + (connector === active ? "border-accent-hover text-heading" : "border-transparent text-fg-muted hover:text-fg")}>
          <GitBranch size={13} aria-hidden />{connector.title}
        </button>)}
      </div>
      <div role="tabpanel" id={`vcs-panel-${active.provider}`} aria-labelledby={`vcs-tab-${active.provider}`}>
        <HostSettings key={active.provider} connector={active} allowed={allowed} />
      </div>
    </>;
  }
  return <SettingsPage title="Version control" description="Connect code hosts, link references to issues, and configure time mirroring.">
    {body}
  </SettingsPage>;
}

function HostSettings({ connector, allowed }: { connector: VcsConnector; allowed: boolean }) {
  if (!allowed) return <p role="alert" className="text-sm text-fg-muted">{NO_PERMISSION}</p>;
  return <>
    <VcsHostSettings config={connector} />
    <Slot id={SlotId.settingsFooter} history={{ entities: historyEntities(connector.provider) }} />
  </>;
}
