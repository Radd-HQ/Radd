import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Database } from "lucide-react";
import { Callout, EmptyState, ErrorText, SettingsPage, Spinner, useCurrentUser, useIsInstanceAdmin } from "@radd/plugin-sdk";
import { statusQuery } from "./api";
import { Panel } from "./chrome";
import { ConnectionsPanel } from "./ConnectionsPanel";
import { PlanEditor } from "./PlanEditor";
import { PlansPanel } from "./PlansPanel";
import { RunsPanel } from "./RunsPanel";
import { SnapshotsPanel } from "./SnapshotsPanel";

const TITLE = "Import from Jira";
const HISTORY = { entities: ["jira_connection"] };
/** The whole procedure, in the order the page runs it. */
const PROCEDURE =
  "Connect your source → download once → review mappings → check and dry run → import. " +
  "Reopen a saved plan to adjust mappings without downloading again. " +
  "Review the run report before retrying or undoing an import.";

/** Settings → Import → Jira: Connections → Download once → Plan → Dry run → Import → Runs.
 * Each stage is a durable object you can revisit; the download is cached, so fixing a mapping costs no re-download. */
export function JiraImportPage() {
  const me = useCurrentUser();
  const isAdmin = useIsInstanceAdmin();
  const status = useQuery({ ...statusQuery(), enabled: isAdmin });
  const [planId, setPlanId] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ section: string; mappingKey: string; nonce: number } | null>(
    null,
  );

  /** A run problem says which mapping caused it — open that plan, tab and row (the editor scrolls to it). */
  const fixMapping = (targetPlan: string, section: string, mappingKey: string) => {
    setPlanId(targetPlan);
    setFocus({ section, mappingKey, nonce: Date.now() });
  };

  if (!me) {
    return (
      <SettingsPage history={HISTORY} title={TITLE}>
        <Spinner label="Loading…" />
      </SettingsPage>
    );
  }
  if (!isAdmin) {
    return (
      <SettingsPage history={HISTORY} title={TITLE}>
        <EmptyState icon={Database} message="Only instance admins can run a Jira import." />
      </SettingsPage>
    );
  }

  return (
    <SettingsPage history={HISTORY} title={TITLE} description={PROCEDURE}>
      <div className="flex flex-col gap-6" data-jira-import>
        <ConnectionsPanel />

        {status.isPending ? (
          <Spinner label="Checking the Jira connection…" />
        ) : status.isError ? (
          <ErrorText error={status.error} />
        ) : !status.data.configured ? (
          <ConnectionNotice title="No Jira connection yet" detail="Add one above to start an import." />
        ) : !status.data.ok ? (
          <ConnectionNotice
            title={`Cannot reach ${status.data.connection_name || "Jira"}`}
            detail={status.data.error}
          />
        ) : (
          <p className="flex items-center gap-1.5 text-xs text-status-success-ink">
            <CheckCircle2 size={13} />
            Connected to <span className="text-fg">{status.data.connection_name}</span> as{" "}
            <span className="text-fg">{status.data.account}</span>
          </p>
        )}

        <SnapshotsPanel />

        <PlansPanel selectedId={planId} onSelect={setPlanId} />

        {planId && (
          <Panel id="jira-mappings" section="mappings" title="Mappings">
            <PlanEditor key={planId} planId={planId} focus={focus} />
          </Panel>
        )}

        <RunsPanel onRerun={setPlanId} onFix={fixMapping} />
      </div>
    </SettingsPage>
  );
}

function ConnectionNotice({ title, detail }: { title: string; detail: string }) {
  return (
    <Callout kind="warning" className="p-3">
      <p className="text-[13px]">{title}</p>
      {detail && <p className="mt-1 text-fg-secondary">{detail}</p>}
    </Callout>
  );
}
