import { useQuery } from "@tanstack/react-query";
import { Clock } from "lucide-react";
import { errorMessage } from "../../lib/api";
import { itemTimelogQuery } from "../../lib/queries";
import { Spinner } from "../Spinner";

/**
 * The Work-log tab: the item's logged-work history (who logged what, when).
 * Read-only — logging + editing lives in the properties-rail Time-tracking
 * panel; this reuses the same `GET /items/{id}/timelog` summary.
 */
export function WorklogTab({ itemId }: { itemId: string }) {
  const summary = useQuery(itemTimelogQuery(itemId));

  if (summary.isPending) return <Spinner label="Loading worklog…" />;
  if (summary.isError) {
    return <p className="text-xs text-red-400">Failed to load worklog: {errorMessage(summary.error)}</p>;
  }
  const data = summary.data;
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-fg-secondary">
        <span className="font-medium text-heading">{data.logged}</span> logged
        {data.original_estimate ? (
          <>
            {" · "}
            {data.original_estimate} estimated
            {data.remaining ? ` · ${data.remaining} remaining` : ""}
          </>
        ) : null}
      </p>
      {data.entries.length === 0 ? (
        <p className="text-xs text-fg-faint">No work logged yet.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {data.entries.map((entry) => (
            <li key={entry.id} className="flex items-start gap-2.5 text-[13px]">
              <Clock size={13} className="mt-0.5 shrink-0 text-fg-faint" aria-hidden />
              <div className="min-w-0">
                <p className="flex flex-wrap items-baseline gap-x-1.5">
                  <span className="font-medium text-fg">{entry.author.name}</span>
                  <span className="text-fg-secondary">logged</span>
                  <span className="font-medium text-heading">{entry.time_spent}</span>
                  <span className="text-fg-faint">on {entry.worked_on}</span>
                  {entry.category && (
                    <span className="rounded bg-elevated px-1.5 py-px text-[11px] text-fg">
                      {entry.category.name}
                    </span>
                  )}
                </p>
                {entry.note && <p className="text-fg-muted">{entry.note}</p>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
