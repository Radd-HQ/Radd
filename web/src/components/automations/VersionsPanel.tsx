/**
 * Version history (RADD-1268, delivering RADD-1111).
 *
 * Every save that changed what the automation IS wrote an immutable version.
 * This lists them, previews one read-only on its own canvas, and restores one
 * — which writes a NEW version copying it, so history never rewrites. The
 * Drive model, because a bad edit destroying hours of tuning with no way back
 * is what the report described.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitBranch, RotateCcw } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { apiAutomationRestorePath } from "../../lib/constants";
import { automationCatalogQuery, automationVersionQuery, automationVersionsQuery, queryKeys } from "../../lib/queries";
import { relativeTime, shortDateTime } from "../../lib/dates";
import type { AutomationVersion, Rule } from "../../lib/types";
import { Button, ButtonVariant } from "../Button";
import { useConfirm } from "../ConfirmDialog";
import { LazyGraphCanvas } from "./LazyGraphCanvas";

interface VersionsPanelProps {
  ruleId: string;
  /** The current version's number, to mark the row that is live. */
  current: number;
  /** After a restore the editor reloads the automation. */
  onRestored: (rule: Rule) => void;
}

export function VersionsPanel({ ruleId, current, onRestored }: VersionsPanelProps) {
  const queryClient = useQueryClient();
  const catalog = useQuery(automationCatalogQuery);
  const list = useQuery(automationVersionsQuery(ruleId));
  const [selected, setSelected] = useState<number | null>(null);
  const detail = useQuery({ ...automationVersionQuery(ruleId, selected ?? 0), enabled: selected !== null });
  const [confirmDialog, confirm] = useConfirm();

  const restore = useMutation({
    mutationFn: (version: number) =>
      api.post<Rule>(apiAutomationRestorePath(ruleId, version), { note: `Restored version ${version}` }),
    onSuccess: async (rule) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.automations });
      setSelected(null);
      onRestored(rule);
    },
  });

  const onRestore = async (row: AutomationVersion) => {
    const ok = await confirm({
      title: `Restore version ${row.version}?`,
      message: `The automation becomes what it was at v${row.version} (${row.node_count} nodes). This writes a new version rather than deleting anything, so the versions after it stay in the history.`,
      confirmLabel: "Restore",
    });
    if (ok) restore.mutate(row.version);
  };

  return (
    <div className="flex flex-col gap-3 rounded-md border border-subtle bg-surface/40 p-3" data-versions-panel>
      {confirmDialog}
      <div className="flex items-center gap-2">
        <GitBranch size={14} className="text-accent-text" aria-hidden />
        <span className="text-xs font-medium text-fg">Versions</span>
        <span className="text-[11px] text-fg-muted">
          Every save that changed the graph or the name. Restoring writes a new version; nothing is lost.
        </span>
      </div>

      {list.isPending && <p className="text-xs text-fg-muted">Loading versions…</p>}
      {list.data && (
        <ul className="flex flex-col gap-0.5" data-versions-list>
          {list.data.map((row) => (
            <li key={row.id}>
              <div
                data-version-row={row.version}
                className={`flex w-full flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded border px-2.5 py-1.5 text-xs ${
                  row.version === selected ? "border-emphasis bg-elevated" : "border-subtle/80 bg-base/40"
                }`}
              >
                <button
                  type="button"
                  onClick={() => setSelected(row.version === selected ? null : row.version)}
                  aria-expanded={row.version === selected}
                  className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-0.5 text-left cursor-pointer"
                >
                  <span className="font-medium text-fg">v{row.version}</span>
                  {row.version === current && (
                    <span data-version-current className="rounded bg-emerald-500/15 px-1.5 py-px text-[10px] uppercase tracking-wide text-emerald-300">
                      current
                    </span>
                  )}
                  <span className="text-[11px] text-fg-secondary" title={shortDateTime(row.created_at)}>
                    {relativeTime(row.created_at)}
                  </span>
                  {row.created_by_name && <span className="text-[11px] text-fg-muted">by {row.created_by_name}</span>}
                  <span className="text-[11px] text-fg-muted">{row.node_count} nodes · {row.name}</span>
                  {row.restored_from !== null && (
                    <span className="text-[11px] text-fg-faint">restored from v{row.restored_from}</span>
                  )}
                  {row.note && <span className="w-full text-[11px] text-fg-secondary">{row.note}</span>}
                </button>
                {row.version !== current && (
                  <Button
                    variant={ButtonVariant.ghost}
                    size="sm"
                    aria-label={`Restore version ${row.version}`}
                    disabled={restore.isPending}
                    onClick={() => void onRestore(row)}
                  >
                    <RotateCcw size={12} aria-hidden />
                    Restore
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {restore.isError && <p className="text-xs text-status-danger">{errorMessage(restore.error)}</p>}

      {selected !== null && detail.data && detail.data.version === selected && (
        <div data-version-preview={selected} className="flex flex-col gap-1">
          <p className="text-[11px] uppercase tracking-wide text-fg-muted">
            v{selected} — read only
          </p>
          <LazyGraphCanvas
            nodes={detail.data.nodes}
            edges={detail.data.edges}
            orientation={detail.data.orientation}
            catalog={catalog.data}
            readOnly
          />
        </div>
      )}
    </div>
  );
}
