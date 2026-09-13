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
  const [planId, setPlanId] = useState("");
  const [focus, setFocus] = useState<{
    section: ConfluenceMappingSection;
    key: string;
    nonce: number;
  } | null>(null);

  const plans = useQuery(confluencePlansQuery());

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

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-lg font-semibold text-heading">Import from Confluence</h1>
        <p className="text-[13px] text-fg-muted">
          Download a space, a section or a set of pages once, decide what its macros
          and restrictions become, then import — reversibly.
        </p>
      </header>

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
        <PlanEditor
          planId={planId}
          focus={focus}
          onRan={() => {
            void client.invalidateQueries({ queryKey: queryKeys.confluenceRuns });
          }}
        />
      )}

      <RunsPanel
        onFix={(section, key) => {
          setFocus({ section, key, nonce: Date.now() });
          document
            .getElementById("confluence-mappings")
            ?.scrollIntoView({ behavior: "smooth", block: "start" });
        }}
      />
    </div>
  );
}
