import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, Database } from "lucide-react";
import { useCurrentUser } from "../../lib/hooks";
import { InstanceRole } from "../../lib/types";
import { jiraStatusQuery } from "../../lib/queries";
import { EmptyState } from "../../components/EmptyState";
import { Spinner } from "../../components/Spinner";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { ConnectionsPanel } from "../../components/settings/jira/ConnectionsPanel";
import { PlanEditor } from "../../components/settings/jira/PlanEditor";
import { PlansPanel } from "../../components/settings/jira/PlansPanel";
import { RunsPanel } from "../../components/settings/jira/RunsPanel";
import { SnapshotsPanel } from "../../components/settings/jira/SnapshotsPanel";
import { ErrorText } from "../../components/ErrorText";
import { Callout } from "../../components/Callout";

/**
 * Import from Jira (spec 100) — a cache-first pipeline, in the order it runs.
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
  const isAdmin = me?.instance_role === InstanceRole.admin;
  const status = useQuery(jiraStatusQuery(isAdmin));
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

  if (!isAdmin) {
    return (
      <SettingsPage title="Import from Jira">
        <EmptyState icon={Database} message="Only instance admins can run a Jira import." />
      </SettingsPage>
    );
  }

  return (
    <SettingsPage
      title="Import from Jira"
      description="Download a Jira project once, decide every mapping, preview the result, then import. Nothing is guessed silently, and an import can be undone."
    >
      <div className="flex flex-col gap-6">
        <ConnectionsPanel />

        {status.isPending ? (
          <Spinner label="Checking the Jira connection…" />
        ) : status.isError ? (
          <ErrorText error={status.error} />
        ) : !status.data.configured ? (
          <ConnectionNotice
            title="No Jira connection yet"
            detail="Add one above to start an import."
          />
        ) : !status.data.ok ? (
          <ConnectionNotice
            title={`Cannot reach ${status.data.connection_name || "Jira"}`}
            detail={status.data.error}
          />
        ) : (
          <p className="flex items-center gap-1.5 text-xs text-emerald-400">
            <CheckCircle2 size={13} />
            Connected to <span className="text-fg">{status.data.connection_name}</span> as{" "}
            <span className="text-fg">{status.data.account}</span>
          </p>
        )}

        {/* Jira is read ONCE into a local cache; every later step works offline. */}
        <SnapshotsPanel />

        <PlansPanel selectedId={planId} onSelect={setPlanId} />

        {planId && (
          <section id="jira-mappings" className="rounded-lg border border-subtle bg-surface p-4">
            <h2 className="mb-3 text-[13px] font-medium text-heading">Mappings</h2>
            <PlanEditor planId={planId} onRunStarted={() => undefined} focus={focus} />
          </section>
        )}

        <RunsPanel onRerun={setPlanId} onFix={fixMapping} />
      </div>
    </SettingsPage>
  );
}

function ConnectionNotice({ title, detail }: { title: string; detail: string }) {
  return (
    <Callout kind="warning" icon={CircleAlert} className="p-3">
      <p className="text-[13px]">{title}</p>
      {detail && <p className="mt-1 text-fg-secondary">{detail}</p>}
    </Callout>
  );
}
