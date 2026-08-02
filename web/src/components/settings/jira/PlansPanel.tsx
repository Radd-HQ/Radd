import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ClipboardList, Trash2 } from "lucide-react";
import { api, errorMessage } from "../../../lib/api";
import { ApiPath } from "../../../lib/constants";
import {
  jiraPlansQuery,
  jiraSnapshotsQuery,
  queryKeys,
} from "../../../lib/queries";
import { SnapshotStage, type JiraPlan } from "../../../lib/types";
import { Button } from "../../Button";
import { useConfirm } from "../../ConfirmDialog";
import { EmptyState } from "../../EmptyState";
import { Modal } from "../../Modal";
import { QueryError } from "../../QueryError";
import { SelectField } from "../../SelectField";
import { Table, TBody, Td, THead, Th } from "../../Table";
import { TableSkeleton } from "../../TableSkeleton";
import { TextField } from "../../TextField";

/**
 * Import plans (spec 100) — one per cached download, holding every mapping
 * decision. Creating one PROFILES the snapshot and pre-fills all nine tables, so
 * the mapping step opens on suggestions rather than a blank sheet.
 */
export function PlansPanel({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (planId: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const plans = useQuery(jiraPlansQuery());
  const [adding, setAdding] = useState(false);
  const [confirmNode, confirm] = useConfirm();

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: queryKeys.jiraPlans });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${ApiPath.jiraPlans}/${id}`),
    onSuccess: (_data, id) => {
      if (selectedId === id) onSelect(null);
      invalidate();
    },
  });

  const onDelete = async (plan: JiraPlan) => {
    const ok = await confirm({
      title: `Delete the plan “${plan.name}”?`,
      message:
        "Only the mapping decisions are removed. Anything already imported stays, and the cached download is untouched.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (ok) remove.mutate(plan.id);
  };

  return (
    <section className="rounded-lg border border-subtle bg-surface p-4">
      {confirmNode}
      <header className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-[13px] font-medium text-heading">Import plans</h2>
          <p className="mt-0.5 text-xs text-fg-secondary">
            Every mapping decision for one cached download — edit it, dry-run it, import it.
          </p>
        </div>
        <Button size="sm" className="shrink-0 whitespace-nowrap" onClick={() => setAdding(true)}>
          New plan
        </Button>
      </header>

      {plans.isPending ? (
        <TableSkeleton rows={2} />
      ) : plans.isError ? (
        <QueryError label="import plans" error={plans.error} />
      ) : plans.data.length === 0 ? (
        <EmptyState
          icon={ClipboardList}
          message="No plans yet — create one from a cached download to start mapping."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <Table>
            <THead>
              <tr>
                <Th>Plan</Th>
                <Th>Target project</Th>
                <Th>Targets created</Th>
                <Th className="text-right">Actions</Th>
              </tr>
            </THead>
            <TBody>
              {plans.data.map((plan) => (
                <tr key={plan.id} className={selectedId === plan.id ? "bg-overlay" : undefined}>
                  <Td>
                    <button
                      type="button"
                      onClick={() => onSelect(plan.id)}
                      className="text-left text-heading hover:text-accent-text cursor-pointer"
                    >
                      {plan.name}
                    </button>
                  </Td>
                  <Td className="whitespace-nowrap font-mono text-xs text-fg-secondary">
                    {plan.radd_project_key}
                  </Td>
                  <Td className="whitespace-nowrap text-xs">
                    {plan.provisioned_at ? (
                      <span className="flex items-center gap-1.5 text-emerald-400">
                        <CheckCircle2 size={13} /> Provisioned
                      </span>
                    ) : (
                      <span className="text-fg-faint">Not yet</span>
                    )}
                  </Td>
                  <Td>
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        size="sm"
                        variant={selectedId === plan.id ? "primary" : "secondary"}
                        onClick={() => onSelect(plan.id)}
                      >
                        {selectedId === plan.id ? "Editing" : "Edit mappings"}
                      </Button>
                      <Button
                        size="sm"
                        variant="danger-ghost"
                        aria-label={`Delete ${plan.name}`}
                        onClick={() => void onDelete(plan)}
                      >
                        <Trash2 size={13} />
                      </Button>
                    </div>
                  </Td>
                </tr>
              ))}
            </TBody>
          </Table>
        </div>
      )}

      {adding && (
        <NewPlanModal
          onClose={() => setAdding(false)}
          onCreated={(plan) => {
            invalidate();
            onSelect(plan.id);
          }}
        />
      )}
    </section>
  );
}

function NewPlanModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (plan: JiraPlan) => void;
}) {
  const snapshots = useQuery(jiraSnapshotsQuery());
  const ready = (snapshots.data ?? []).filter((s) => s.stage === SnapshotStage.done);
  const [snapshotId, setSnapshotId] = useState("");
  const [name, setName] = useState("");
  const [projectKey, setProjectKey] = useState("");
  const [projectName, setProjectName] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.post<JiraPlan>(ApiPath.jiraPlans, {
        name,
        snapshot_id: snapshotId,
        radd_project_key: projectKey,
        radd_project_name: projectName,
      }),
    onSuccess: (plan) => {
      onCreated(plan);
      onClose();
    },
  });

  const pickSnapshot = (id: string) => {
    setSnapshotId(id);
    const snapshot = ready.find((s) => s.id === id);
    if (!snapshot) return;
    // Sensible defaults from the download itself; all still editable.
    setName((current) => current || `Import ${snapshot.jira_project_key}`);
    setProjectKey((current) => current || snapshot.jira_project_key.slice(0, 10).toUpperCase());
    setProjectName((current) => current || snapshot.jira_project_key);
  };

  return (
    <Modal title="New import plan" onClose={onClose}>
      <div className="flex flex-col gap-3">
        <SelectField
          label="Cached download"
          value={snapshotId}
          onChange={(e) => pickSnapshot(e.target.value)}
          hint={
            ready.length === 0
              ? "No completed downloads yet — download a project first."
              : "The plan is pre-filled by profiling this download."
          }
        >
          <option value="">Pick a download…</option>
          {ready.map((snapshot) => (
            <option key={snapshot.id} value={snapshot.id}>
              {snapshot.name} — {snapshot.issue_count} issues
            </option>
          ))}
        </SelectField>
        <TextField label="Plan name" value={name} onChange={(e) => setName(e.target.value)} />
        <TextField
          label="Radd project key"
          value={projectKey}
          onChange={(e) => setProjectKey(e.target.value.toUpperCase())}
          hint="Letters and digits, max 10. Issues keep their Jira numbers under this key."
        />
        <TextField
          label="Radd project name"
          value={projectName}
          onChange={(e) => setProjectName(e.target.value)}
        />
        {create.isError && <p className="text-xs text-red-400">{errorMessage(create.error)}</p>}
        <div className="mt-1 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => create.mutate()}
            disabled={!snapshotId || !name || !projectKey || !projectName || create.isPending}
          >
            {create.isPending ? "Profiling the download…" : "Create plan"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
