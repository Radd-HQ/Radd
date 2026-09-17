import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BookUp, DatabaseZap } from "lucide-react";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { QueryError } from "../../components/QueryError";
import { Spinner } from "../../components/Spinner";
import { useCurrentUser } from "../../lib/hooks";
import { capabilitiesQuery } from "../../lib/queries";
import { RoutePath } from "../../lib/constants";
import { InstanceRole } from "../../lib/types";

const importers = [
  { plugin: "jiraimport", title: "Jira", icon: DatabaseZap, to: RoutePath.settingsJiraImport, description: "Import project issues, people, sprints, comments and attachments with editable field and status mappings." },
  { plugin: "confluenceimport", title: "Confluence", icon: BookUp, to: RoutePath.settingsConfluenceImport, description: "Import Server / Data Center spaces or selected page trees, including macros, attachments and page restrictions. Confluence Cloud is not supported." },
];

export function ImportDataPage() {
  const me = useCurrentUser();
  const manifest = useQuery(capabilitiesQuery);
  return <SettingsPage title="Import data" description="Bring existing work and documentation into Radd.">
    {me?.instance_role !== InstanceRole.admin ? <p>Only instance admins can import data.</p> : <>
      <p className="mb-5 text-sm text-fg-muted">Connect your source → download once → review mappings → check and dry run → import. Reopen a saved plan to adjust mappings without downloading again. Review the run report before retrying or undoing an import.</p>
      {manifest.isError ? <QueryError label="available importers" error={manifest.error}/> : manifest.isPending ? <Spinner label="Loading importers…"/> :
        <div className="grid gap-4 md:grid-cols-2">{importers.map(({plugin,title,icon: Icon,to,description}) => <section key={plugin} className="rounded-lg border border-subtle bg-surface p-4">
          <h3 className="mb-2 flex items-center gap-2 font-semibold text-heading"><Icon size={18}/>{title}</h3>
          <p className="mb-4 text-sm text-fg-muted">{description}</p>
          {manifest.data.plugins.includes(plugin) ? <Link to={to} className="text-sm text-accent-text hover:underline">Open {title} importer →</Link> : <Link to={RoutePath.settingsPlugins} className="text-sm text-accent-text hover:underline">Enable importer in Plugins →</Link>}
        </section>)}</div>}
    </>}
  </SettingsPage>;
}
