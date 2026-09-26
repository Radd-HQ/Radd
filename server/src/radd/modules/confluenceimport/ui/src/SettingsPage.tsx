import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, todayIso, useCurrentUser, useIsInstanceAdmin, Button, ButtonVariant, QueryError, SettingsPage, Spinner } from "@radd/plugin-sdk";
import { ConnectionsPanel } from "./ConnectionsPanel";
import { PlanEditor } from "./PlanEditor";
import { RunsPanel } from "./RunsPanel";
import { SnapshotsPanel } from "./SnapshotsPanel";
import { ConfluencePath, confluenceKeys, plansQuery } from "./queries";
import type { ConfluenceMappingSection, ConfluenceSnapshot } from "./types";

const TITLE = "Import from Confluence";
const DESCRIPTION =
  "Connect your Confluence Server or Data Center → download spaces or pages once → review mappings → " +
  "check and dry run → import. Reopen a saved plan to adjust mappings without downloading again. Review " +
  "the run report before retrying or undoing an import. Confluence Cloud is not supported.";

/** Import from Confluence — one scrolling page, like the Jira importer: fixing a mapping and re-running
 * against the same cached download is a loop, not a funnel. */
export function ConfluenceImportPage() {
  const me = useCurrentUser();
  const isAdmin = useIsInstanceAdmin();
  const client = useQueryClient();
  const [planId, setPlanId] = useState("");
  const [focus, setFocus] = useState<{
    section: ConfluenceMappingSection;
    key: string;
    nonce: number;
  } | null>(null);

  const plans = useQuery({ ...plansQuery(), enabled: isAdmin });

  const createPlan = useMutation({
    mutationFn: (snapshot: ConfluenceSnapshot) =>
      api.post<{ id: string }>(ConfluencePath.plans, {
        name: `${snapshot.name} — ${todayIso()}`,
        snapshot_id: snapshot.id,
      }),
    onSuccess: (plan) => {
      void client.invalidateQueries({ queryKey: confluenceKeys.plans });
      setPlanId(plan.id);
    },
  });

  const rows = plans.data ?? [];

  // Settings is signed-in only, so no user yet means it is still loading.
  if (!me) return <SettingsPage title={TITLE}><Spinner label="Loading…"/></SettingsPage>;
  if (!isAdmin) return <SettingsPage title={TITLE}><p>Only instance admins can import data.</p></SettingsPage>;
  return (
    <SettingsPage title={TITLE} description={DESCRIPTION} history={{ entities: ["confluence_connection"] }}>
    <div className="flex flex-col gap-4" data-confluence-import>
      {createPlan.isError && <QueryError label="create import plan" error={createPlan.error}/>}
      {plans.isError && <QueryError label="import plans" error={plans.error}/>}
      <ConnectionsPanel />

      <SnapshotsPanel onPlanFrom={(snapshot) => createPlan.mutate(snapshot)} />

      {rows.length > 0 && (
        <section className="rounded-xl border border-subtle bg-surface p-4" data-confluence-plans>
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
        <PlanEditor key={planId} planId={planId} focus={focus} />
      )}

      {/* The editor scrolls itself to the row once the plan is open. */}
      <RunsPanel
        onFix={(targetPlan, section, key) => {
          setPlanId(targetPlan);
          setFocus({ section, key, nonce: Date.now() });
        }}
      />

    </div>
    </SettingsPage>
  );
}
