import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { GitBranch } from "lucide-react";
import { SettingsPage, EmptyState, Slot, Spinner, useRemotesLoading, useSlot } from "@radd/plugin-sdk";
import { VCS_PROVIDER_SETTINGS_SLOT } from "./host-contract";
/** VCS owns the workflow; providers contribute their own tabs and configuration. */
export function VcsSettingsPage() {
 const search = useSearch({strict: false}) as {host?: string};
 const navigate = useNavigate();
 const providers = useSlot(VCS_PROVIDER_SETTINGS_SLOT);
 // Connectors are optional remotes: while one may still arrive, wait rather than claim there are
 // none or that the requested one is unavailable (RADD-1373).
 const loading = useRemotesLoading();
 const requestedMissing = Boolean(search.host) && !providers.some(entry => entry.contribution.match === search.host);
 const active = providers.find(entry => entry.contribution.match === search.host) ?? providers[0];
 if (loading && (providers.length === 0 || requestedMissing)) {
  return <SettingsPage title="Version control" description="Connect code hosts, link references to issues, and configure time mirroring."><div role="status" className="flex items-center gap-2 text-sm text-fg-muted"><Spinner />Loading connectors…</div></SettingsPage>;
 }
 const select = (host: string) => void navigate({to: "/settings/$", params: {_splat: "vcs"}, search: {host}, replace: true});
 return <SettingsPage title="Version control" description="Connect code hosts, link references to issues, and configure time mirroring.">
  {!active ? <EmptyState icon={GitBranch} message="No version control connectors are available." action={<Link to="/settings/plugins" className="text-accent-text hover:underline">Manage plugins →</Link>} /> : <>
   {search.host && active.contribution.match !== search.host && <p className="mb-3 text-sm text-fg-muted">The requested connector is unavailable. Showing {active.contribution.title}.</p>}
   <div role="tablist" aria-label="Version control hosts" className="mb-5 flex flex-wrap gap-1 border-b border-subtle">
    {providers.map(entry => <button key={`${entry.plugin}:${entry.contribution.id}`} type="button" role="tab"
     id={`vcs-tab-${entry.contribution.match}`} aria-controls={`vcs-panel-${entry.contribution.match}`} aria-selected={entry === active}
     onClick={() => select(entry.contribution.match!)}
     className={"-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-[13px] cursor-pointer focus-visible:outline-2 focus-visible:outline-focus " + (entry === active ? "border-accent-hover text-heading" : "border-transparent text-fg-muted hover:text-fg")}>
     <GitBranch size={13} aria-hidden />{entry.contribution.title}
    </button>)}
   </div>
   <div role="tabpanel" id={`vcs-panel-${active.contribution.match}`} aria-labelledby={`vcs-tab-${active.contribution.match}`}>
    <Slot id={VCS_PROVIDER_SETTINGS_SLOT} match={active.contribution.match} errorFallback={<p role="alert">This connector's settings could not be loaded.</p>} />
   </div>
  </>}
 </SettingsPage>;
}
