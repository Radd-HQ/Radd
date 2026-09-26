import { useQuery } from "@tanstack/react-query";
import { SlaTimerChip } from "./SlaChips";
import { itemSlaQuery } from "./timers";

/**
 * The issue rail's SLA section (spec 30): rendered only when a policy applies to the item — the
 * item's MATCHED policy since spec 63 (at most one entry). Live server compute, re-read every
 * minute and on every item change (the `item` tag).
 */
export function SlaPanel({ itemId }: { itemId: string }) {
  const { data } = useQuery(itemSlaQuery(itemId));
  if (!data || data.entries.length === 0) return null;
  return (
    <div className="p-4" data-plugin-section="slas">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-fg-muted">SLA</h3>
      <div className="flex flex-col gap-2">
        {data.entries.map((entry) => (
          <div key={entry.policy_id}>
            <p className="mb-1 text-[11px] text-fg-muted">{entry.policy_name}</p>
            <ul className="flex flex-col gap-1">
              {entry.timers.map((timer) => (
                <li key={timer.kind} className="flex items-center gap-2 text-xs">
                  <span className="capitalize text-fg-secondary">{timer.kind}</span>
                  <SlaTimerChip timer={timer} className="ml-auto" />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
