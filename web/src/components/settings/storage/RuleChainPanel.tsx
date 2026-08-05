import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, CornerDownRight, Pencil, Plus, Trash2 } from "lucide-react";
import { api } from "../../../lib/api";
import { ApiPath, apiStorageRulePath } from "../../../lib/constants";
import { queryKeys, storageHostsQuery, storageRulesQuery } from "../../../lib/queries";
import {
  StorageRuleType,
  type StorageRuleRead,
  type StorageRuleTypeValue,
} from "../../../lib/types";
import { Button } from "../../Button";
import { useConfirm } from "../../ConfirmDialog";
import { DropdownMenu } from "../../DropdownMenu";
import { QueryError } from "../../QueryError";
import { TableSkeleton } from "../../TableSkeleton";
import { RuleDialog } from "./RuleDialog";
import { ErrorText } from "../../ErrorText";

const TYPE_LABELS: Record<StorageRuleTypeValue, string> = {
  [StorageRuleType.userChoice]: "Ask the uploader",
  [StorageRuleType.cidr]: "Network (CIDR)",
  [StorageRuleType.llm]: "AI classifier",
};

const sectionHeadClasses = "mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted";

/** One-line gloss of what a rule does, from its config. */
function ruleSummary(rule: StorageRuleRead, hostName: (id: string) => string): string {
  if (rule.rule_type === StorageRuleType.cidr) {
    const ranges = rule.config.ranges ?? [];
    return ranges.map((range) => `${range.cidr} → ${hostName(range.host_id)}`).join(" · ");
  }
  if (rule.rule_type === StorageRuleType.llm) {
    const answers = rule.config.answers ?? [];
    const prefixes = (rule.config.content_type_prefixes ?? []).join(", ");
    return (
      answers.map((entry) => `“${entry.answer}” → ${hostName(entry.host_id)}`).join(" · ") +
      (prefixes ? ` (${prefixes})` : "")
    );
  }
  return "Prompts the uploader to pick a user-selectable host; no answer falls through.";
}

/**
 * The routing chain (spec 102): position-ordered rules every upload walks
 * top-down — the first that answers picks the host, everything unmatched lands
 * on the default host (the terminal pseudo-row). Reordering PUTs the full id
 * list; enable/disable is per-row.
 */
export function RuleChainPanel() {
  const rules = useQuery(storageRulesQuery());
  const hosts = useQuery(storageHostsQuery());
  const queryClient = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const [editing, setEditing] = useState<StorageRuleRead | null>(null);
  const [adding, setAdding] = useState(false);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.storageRules });
    // Chain edits change whether/what the upload seams prompt.
    void queryClient.invalidateQueries({ queryKey: queryKeys.storageUploadContext });
  };

  const reorder = useMutation({
    mutationFn: (ids: string[]) =>
      api.put<StorageRuleRead[]>(ApiPath.storageRulesOrder, { ids }),
    onSettled: invalidate,
  });

  const toggle = useMutation({
    mutationFn: (rule: StorageRuleRead) =>
      api.patch<StorageRuleRead>(apiStorageRulePath(rule.id), { enabled: !rule.enabled }),
    onSettled: invalidate,
  });

  const remove = useMutation({
    mutationFn: (ruleId: string) => api.delete<void>(apiStorageRulePath(ruleId)),
    onSettled: invalidate,
  });

  const list = rules.data ?? [];
  const hostList = hosts.data ?? [];
  const hostName = (id: string) =>
    hostList.find((host) => host.id === id)?.name ?? "unknown host";
  const defaultHost = hostList.find((host) => host.is_default);

  const move = (index: number, delta: number) => {
    const ids = list.map((rule) => rule.id);
    const [moved] = ids.splice(index, 1);
    ids.splice(index + delta, 0, moved);
    reorder.mutate(ids);
  };

  const onDelete = async (rule: StorageRuleRead) => {
    const ok = await confirm({
      title: "Delete routing rule",
      message: `Delete "${rule.name}"? Uploads it used to claim fall through to the rest of the chain.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (ok) remove.mutate(rule.id);
  };

  return (
    <section className="mt-8">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className={`${sectionHeadClasses} mb-0`}>Routing rules</h2>
        <Button onClick={() => setAdding(true)}>
          <Plus size={14} aria-hidden />
          Add rule
        </Button>
      </div>
      <p className="mb-3 text-xs text-fg-muted">
        Every upload walks this chain top-down; the first rule that answers picks the host.
        Rules only narrow where bytes go — they never block an upload.
      </p>
      {rules.isPending ? (
        <TableSkeleton rows={2} />
      ) : rules.isError ? (
        <QueryError label="routing rules" error={rules.error} />
      ) : (
        <ul className="rounded-lg border border-subtle">
          {list.map((rule, index) => (
            <li
              key={rule.id}
              className="flex items-center gap-2.5 border-b border-subtle/60 px-3 py-2"
            >
              <span className="flex flex-col">
                <button
                  type="button"
                  onClick={() => move(index, -1)}
                  disabled={index === 0 || reorder.isPending}
                  aria-label={`Move ${rule.name} up`}
                  className="rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer disabled:opacity-30 disabled:pointer-events-none"
                >
                  <ArrowUp size={12} aria-hidden />
                </button>
                <button
                  type="button"
                  onClick={() => move(index, 1)}
                  disabled={index === list.length - 1 || reorder.isPending}
                  aria-label={`Move ${rule.name} down`}
                  className="rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer disabled:opacity-30 disabled:pointer-events-none"
                >
                  <ArrowDown size={12} aria-hidden />
                </button>
              </span>
              <input
                type="checkbox"
                checked={rule.enabled}
                onChange={() => toggle.mutate(rule)}
                disabled={toggle.isPending}
                aria-label={`Enable ${rule.name}`}
                title={rule.enabled ? "Enabled — uploads consult this rule" : "Disabled — skipped"}
                className="size-3.5 accent-accent"
              />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span
                    className={
                      "text-[13px] font-medium " +
                      (rule.enabled ? "text-heading" : "text-fg-faint")
                    }
                  >
                    {rule.name}
                  </span>
                  <span className="rounded bg-elevated px-1.5 py-px text-[10px] text-fg-secondary">
                    {TYPE_LABELS[rule.rule_type]}
                  </span>
                </span>
                <span className="block truncate text-xs text-fg-muted">
                  {ruleSummary(rule, hostName)}
                </span>
              </span>
              <DropdownMenu
                label={`Actions for ${rule.name}`}
                align="end"
                items={[
                  {
                    kind: "action",
                    label: "Edit",
                    icon: Pencil,
                    onSelect: () => setEditing(rule),
                  },
                  { kind: "separator" },
                  {
                    kind: "action",
                    label: "Delete",
                    icon: Trash2,
                    danger: true,
                    onSelect: () => void onDelete(rule),
                  },
                ]}
              />
            </li>
          ))}
          {/* The terminal pseudo-row: what happens when no rule answered. */}
          <li className="flex items-center gap-2 px-3 py-2 text-[13px] text-fg-muted">
            <CornerDownRight size={13} className="shrink-0 text-fg-faint" aria-hidden />
            <span>Everything else</span>
            <span aria-hidden>→</span>
            {defaultHost ? (
              <span className="font-medium text-fg">{defaultHost.name}</span>
            ) : (
              <span className="text-amber-300">no default host — set one above</span>
            )}
          </li>
        </ul>
      )}
      {(reorder.isError || toggle.isError || remove.isError) && (
        <ErrorText className="mt-2" error={reorder.error ?? toggle.error ?? remove.error} />
      )}
      {(adding || editing) && (
        <RuleDialog
          existing={editing}
          hosts={hostList}
          onClose={() => {
            setAdding(false);
            setEditing(null);
          }}
        />
      )}
      {confirmDialog}
    </section>
  );
}
