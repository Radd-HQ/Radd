import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { apiCycleCompletePath } from "../../lib/constants";
import { cycleLabel } from "../../lib/cycle-series";
import { Entity, invalidateEntities } from "../../lib/cache";
import { CycleStatus, type Cycle, type CycleComplete, type CycleCompleteResult } from "../../lib/types";
import { ToastKind, pushToast } from "../../lib/toast";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { Select } from "../Select";
import { useCycleDirectory } from "../../lib/useCycleDirectory";
import { DirectoryPager } from "../DirectoryPager";
import { TextField } from "../TextField";
import { ErrorText } from "../ErrorText";

const BACKLOG = "__backlog__";

interface Props {
  cycle: Cycle;
  /** Open-item count when the caller already knows it (the cycle page does). */
  openCount?: number;
  onClose: () => void;
}

/**
 * "Complete cycle" dialog (Jira-style close): choose where open items go — future
 * cycles or the backlog, and whether to start the target now. Server search
 * starts with the same series and can be cleared to select another series.
 */
export function CompleteCycleModal({ cycle, openCount, onClose }: Props) {
  const queryClient = useQueryClient();
  const directory = useCycleDirectory({ includeCompleted: false, excludeId: cycle.id,
    initialFilter: cycleLabel(cycle.name) ?? "" });
  const [target, setTarget] = useState("");
  const [selectedCycle, setSelectedCycle] = useState<Cycle | null>(null);
  const [startNext, setStartNext] = useState(true);
  const toBacklog = target === BACKLOG;
  const targetCycle = selectedCycle;
  const targets = selectedCycle && !directory.rows.some(row => row.id === selectedCycle.id)
    ? [selectedCycle, ...directory.rows] : directory.rows;

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
          if (target) complete.mutate();
        }}
        className="flex flex-col gap-4"
      >
        <p className="text-[13px] text-fg-secondary">
          {openCount !== undefined
            ? `${openCount} open ${openCount === 1 ? "item" : "items"} (not done) will be moved.`
            : "Open items (not done) will be moved."}{" "}
          Completed items stay in this cycle for reporting.
        </p>

        <TextField label="Find a destination cycle" value={directory.filter}
          onChange={event => directory.setFilter(event.target.value)} placeholder="Search cycles by name…"
          hint="Search starts with this series. Clear it to find other cycles; completed cycles are excluded." />
        {directory.isError && <ErrorText error={directory.error} />}
        <label className="flex flex-col gap-1 text-xs text-fg-secondary">
          Move open items to
          <Select
            value={target}
            aria-label="Destination cycle"
            searchable={false}
            onChange={value => { setTarget(value); setSelectedCycle(targets.find(row => row.id === value) ?? null); }}
            placeholder={directory.isPending ? "Loading destinations…" : "Choose a destination"}
            options={[
              ...targets.map((c) => ({
                value: c.id,
                label: `${c.name}${c.status === CycleStatus.draft ? " (draft)" : ""}`,
              })),
              { value: BACKLOG, label: "Backlog (no cycle)" },
            ]}
          />
        </label>

        <DirectoryPager {...directory} onPage={directory.setPage} label="destination cycles" />
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
          <Button type="submit" disabled={complete.isPending || !target}>
            {complete.isPending ? "Completing…" : "Complete cycle"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
