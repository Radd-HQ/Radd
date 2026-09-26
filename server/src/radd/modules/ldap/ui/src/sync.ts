import { formatDateTime } from "@radd/plugin-sdk";
import type { DirectorySyncState } from "./types";

/** One sync's last-run line: timestamp + the numeric summary + error count. */
export function lastRunLine(state: DirectorySyncState | null | undefined): string {
  if (!state) return "Never ran.";
  const counts = Object.entries(state.last_result)
    .filter((entry): entry is [string, number] => typeof entry[1] === "number")
    .map(([key, value]) => `${value} ${key.replace(/_/g, " ")}`)
    .join(" · ");
  const errors = Array.isArray(state.last_result.errors) ? state.last_result.errors.length : 0;
  const errorSuffix = errors > 0 ? ` · ${errors} error${errors === 1 ? "" : "s"}` : "";
  return `Last run ${formatDateTime(state.last_run_at)}: ${counts}${errorSuffix}`;
}

export const sectionHeadClasses = "mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted";
