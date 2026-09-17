import { useCurrentUser } from "../../lib/hooks";
import { InstanceRole } from "../../lib/types";
import { QueryError } from "../../components/QueryError";
import { Link } from "@tanstack/react-router";
import { RoutePath } from "../../lib/constants";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, ButtonVariant } from "../../components/Button";
import { ConnectionsPanel } from "../../components/settings/confluence/ConnectionsPanel";
import { PlanEditor } from "../../components/settings/confluence/PlanEditor";
import { RunsPanel } from "../../components/settings/confluence/RunsPanel";
import { SnapshotsPanel } from "../../components/settings/confluence/SnapshotsPanel";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { confluencePlansQuery, queryKeys } from "../../lib/queries";
import type { ConfluenceSnapshot, ConfluenceMappingSection } from "../../lib/types";
import { todayIso } from "../../lib/dates";
import { SettingsPage } from "../../components/settings/SettingsPage";

/**
 * Import from Confluence (spec 117).
 *
 * ONE scrolling page, not a step wizard — matching the Jira importer. A wizard
 * implies the phases are sequential and disposable; they are not. The whole
 * design is that you fix a mapping and run again against the same cached
 * download, which is a loop, not a funnel.
 */
export function ConfluenceImportPage() {
  const client = useQueryClient();
  const isAdmin = useCurrentUser()?.instance_role === InstanceRole.admin;
  const [planId, setPlanId] = useState("");
  const [focus, setFocus] = useState<{
    section: ConfluenceMappingSection;
    key: string;
    nonce: number;
  } | null>(null);

  const plans = useQuery({ ...confluencePlansQuery(), enabled: isAdmin });

  const createPlan = useMutation({
    mutationFn: (snapshot: ConfluenceSnapshot) =>
      api.post<{ id: string }>(ApiPath.confluencePlans, {
        name: `${snapshot.name} — ${todayIso()}`,
        snapshot_id: snapshot.id,
      }),
    onSuccess: (plan) => {
      void client.invalidateQueries({ queryKey: queryKeys.confluencePlans });
      setPlanId(plan.id);
    },
  });

  const rows = plans.data ?? [];

  if (!isAdmin) return <SettingsPage title="Import from Confluence"><p>Only instance admins can import data.</p></SettingsPage>;
  return (
    <SettingsPage title="Import from Confluence" description="Download Server / Data Center spaces or pages once, review mappings, dry run, then import. Confluence Cloud is not supported." history={{ entities: ["confluence_connection"] }} actions={<Link to={RoutePath.settingsImportData} className="text-sm text-accent-text">← Import data</Link>}>
    <div className="flex flex-col gap-4">
      {createPlan.isError && <QueryError label="create import plan" error={createPlan.error}/>}
      {plans.isError && <QueryError label="import plans" error={plans.error}/>}
      <ConnectionsPanel />

      <SnapshotsPanel onPlanFrom={(snapshot) => createPlan.mutate(snapshot)} />

      {rows.length > 0 && (
        <section className="rounded-xl border border-subtle bg-surface p-4">
          <h2 className="mb-2 text-sm font-semibold text-heading">Plans</h2>
          <ul className="flex flex-wrap gap-2">
            {rows.map((plan) => (
              <li key={plan.id}>
                <Button
                  size="sm"
                  variant={
                    plan.id === planId ? ButtonVariant.primary : ButtonVariant.ghost
                  }
                  onClick={() => setPlanId(plan.id)}
                >
                  {plan.name}
                </Button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {planId && (
        <PlanEditor key={planId}
          planId={planId}
          focus={focus}
          onRan={() => {
            void client.invalidateQueries({ queryKey: queryKeys.confluenceRuns });
          }}
        />
      )}

      <RunsPanel
        onFix={(targetPlan, section, key) => {
          setPlanId(targetPlan);
          setFocus({ section, key, nonce: Date.now() });
          document
            .getElementById("confluence-mappings")
            ?.scrollIntoView({ behavior: "smooth", block: "start" });
        }}
      />

    </div>
    </SettingsPage>
  );
}
