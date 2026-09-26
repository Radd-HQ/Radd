import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Database } from "lucide-react";
import { Callout, EmptyState, ErrorText, SettingsPage, Spinner, useCurrentUser } from "@radd/plugin-sdk";
import { statusQuery } from "./api";
import { ConnectionsPanel } from "./ConnectionsPanel";
import { PlanEditor } from "./PlanEditor";
import { PlansPanel } from "./PlansPanel";
import { RunsPanel } from "./RunsPanel";
import { SnapshotsPanel } from "./SnapshotsPanel";
import { INSTANCE_ADMIN } from "./types";

const TITLE = "Import from Jira";
const HISTORY = { entities: ["jira_connection"] };
/** The whole procedure, in the order the page runs it (it was the Import data hub's line). */
const PROCEDURE =
  "Connect your source → download once → review mappings → check and dry run → import. " +
  "Reopen a saved plan to adjust mappings without downloading again. " +
  "Review the run report before retrying or undoing an import.";

/**
 * Settings → Import → Jira (spec 100; the jiraimport plugin's own page since
 * RADD-1382) — a cache-first pipeline, in the order it runs.
 *
 *   Connections → Download once → Plan every mapping → Dry run → Import → Runs
 *
 * Spec 90 was a one-way four-step wizard that re-paged Jira on every run, decided
 * every mapping for you, and dead-ended permanently once a run started. Here each
 * stage is a durable object you can revisit: the download is cached so a mistake
 * costs nothing to fix, the plan is edited until it is right, the dry run shows
 * the result before committing, and an import can be undone.
 */
export function JiraImportPage() {
  const me = useCurrentUser();
  const isAdmin = me?.instance_role === INSTANCE_ADMIN;
  const status = useQuery({ ...statusQuery(), enabled: isAdmin });
  const [planId, setPlanId] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ section: string; mappingKey: string; nonce: number } | null>(
    null,
  );

  /** A run problem says which mapping caused it — open that plan, tab and row. */
  const fixMapping = (targetPlan: string, section: string, mappingKey: string) => {
    setPlanId(targetPlan);
    setFocus({ section, mappingKey, nonce: Date.now() });
    document.getElementById("jira-mappings")?.scrollIntoView({ behavior: "smooth", block: "start" });
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

        {/* Jira is read ONCE into a local cache; every later step works offline. */}
        <SnapshotsPanel />

        <PlansPanel selectedId={planId} onSelect={setPlanId} />

        {planId && (
          <section id="jira-mappings" className="rounded-lg border border-subtle bg-surface p-4" data-jira-section="mappings">
            <h2 className="mb-3 text-[13px] font-medium text-heading">Mappings</h2>
            <PlanEditor key={planId} planId={planId} onRunStarted={() => undefined} focus={focus} />
          </section>
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
