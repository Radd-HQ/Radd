import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { apiCycleCompletePath } from "../../lib/constants";
import { cycleLabel, sameLabel } from "../../lib/cycle-series";
import { Entity, invalidateEntities } from "../../lib/cache";
import { CycleStatus, type Cycle, type CycleComplete, type CycleCompleteResult } from "../../lib/types";
import { ToastKind, pushToast } from "../../lib/toast";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { Select } from "../Select";
import { ErrorText } from "../ErrorText";

const BACKLOG = "__backlog__";

interface Props {
  cycle: Cycle;
  /** Every cycle — the move-target options come from here. */
  cycles: Cycle[];
  /** Open-item count when the caller already knows it (the cycle page does). */
  openCount?: number;
  onClose: () => void;
}

/**
 * "Complete cycle" dialog (Jira-style close): choose where open items go — future
 * cycles of the SAME LABEL ("PIPE - …"), or the backlog — and whether to start
 * the target now. One-off cycles (no label) offer every future cycle.
 */
export function CompleteCycleModal({ cycle, cycles, openCount, onClose }: Props) {
  const queryClient = useQueryClient();
  const label = cycleLabel(cycle.name);
  const future = cycles.filter((c) => c.id !== cycle.id && c.status !== CycleStatus.completed);
  const sameSeries = future.filter((c) => sameLabel(cycleLabel(c.name), label));
  // Scheduled first (the natural "next"), then drafts, numerically within each.
  const targets = (label !== null && sameSeries.length > 0 ? sameSeries : future).sort((a, b) =>
    a.status === b.status
      ? a.name.localeCompare(b.name, undefined, { numeric: true })
      : a.status === CycleStatus.draft
        ? 1
        : b.status === CycleStatus.draft
          ? -1
          : 0,
  );
  const [target, setTarget] = useState<string>(targets[0]?.id ?? BACKLOG);
  const [startNext, setStartNext] = useState(true);
  const toBacklog = target === BACKLOG;
  const targetCycle = targets.find((c) => c.id === target);

  const complete = useMutation({
    mutationFn: () =>
      api.post<CycleCompleteResult>(apiCycleCompletePath(cycle.id), {
        move_open_to: toBacklog ? null : target,
        start_next: !toBacklog && startNext,
      } satisfies CycleComplete),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["cycles"] });
      invalidateEntities(queryClient, Entity.item);
      const destination = result.next_cycle ? result.next_cycle.name : "the backlog";
      let message = `${cycle.name} completed — ${result.moved_count} open ${
        result.moved_count === 1 ? "item" : "items"
      } moved to ${destination}.`;
      if (result.next_cycle && result.next_cycle.status === CycleStatus.active) {
        message += ` ${result.next_cycle.name} is now active.`;
      }
      if (result.provisioned.length) {
        message += ` Draft${result.provisioned.length === 1 ? "" : "s"} created: ${result.provisioned.join(", ")}.`;
      }
      pushToast(message, ToastKind.success);
      onClose();
    },
  });

  return (
    <Modal title={`Complete ${cycle.name}`} onClose={onClose}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          complete.mutate();
        }}
        className="flex flex-col gap-4"
      >
        <p className="text-[13px] text-fg-secondary">
          {openCount !== undefined
            ? `${openCount} open ${openCount === 1 ? "item" : "items"} (not done) will be moved.`
            : "Open items (not done) will be moved."}{" "}
          Completed items stay in this cycle for reporting.
        </p>

        <label className="flex flex-col gap-1 text-xs text-fg-secondary">
          Move open items to
          <Select
            value={target}
            onChange={setTarget}
            options={[
              ...targets.map((c) => ({
                value: c.id,
                label: `${c.name}${c.status === CycleStatus.draft ? " (draft)" : ""}`,
              })),
              { value: BACKLOG, label: "Backlog (no cycle)" },
            ]}
          />
        </label>

        {!toBacklog && targetCycle && (
          <label className="flex items-center gap-2 text-[13px] text-fg">
            <input
              type="checkbox"
              checked={startNext}
              onChange={(event) => setStartNext(event.target.checked)}
              className="size-3.5 accent-accent"
            />
            Start {targetCycle.name} today
            {targetCycle.status === CycleStatus.draft && (
              <span className="text-[11px] text-fg-muted">(it gets dates starting now)</span>
            )}
          </label>
        )}

        {complete.isError && (
          <ErrorText error={complete.error} />
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={complete.isPending}>
            {complete.isPending ? "Completing…" : "Complete cycle"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
