import { UserRound } from "lucide-react";
import { formatAge } from "../../lib/queue";
import type { Item, SlaBatchTimer } from "../../lib/types";
import { SlaRowChip } from "./SlaChips";

/**
 * The queue-specific row columns (spec 64, fixed set): reporter, age since
 * creation, and the ALWAYS-ON nearest-to-breach SLA chip (spec 63 batch
 * timers). Every column has a FIXED width so consecutive rows align into
 * scannable columns instead of zigzagging with content width.
 */
export function QueueRowMeta({ item, sla }: { item: Item; sla?: SlaBatchTimer[] }) {
  return (
    <>
      <span
        title={item.reporter ? `Reporter: ${item.reporter.name}` : "No reporter"}
        className="inline-flex w-36 shrink-0 items-center gap-1 text-[11px] text-fg-muted"
      >
        <UserRound size={11} aria-hidden className="shrink-0" />
        <span className="truncate">{item.reporter?.name ?? "—"}</span>
      </span>
      <span
        title={`Created ${new Date(item.created_at).toLocaleString()}`}
        className="w-11 shrink-0 text-right font-mono text-[11px] text-fg-muted"
      >
        {formatAge(item.created_at)}
      </span>
      {/* Fixed slot whether or not a policy matched — the columns after it
          (priority/assignee/state) stay put on every row. */}
      <span className="inline-flex w-24 shrink-0 items-center justify-end">
        <SlaRowChip timers={sla} />
      </span>
    </>
  );
}
