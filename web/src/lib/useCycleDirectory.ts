import { useDirectory } from "./useDirectory";
import { cyclesPageQuery, CYCLES_PAGE_SIZE } from "@radd-plugin-ui/cycles/directory-queries";
import type { CycleStatusValue } from "@radd-plugin-ui/cycles/types";

/** One visible cycle window; filters never operate on a truncated local list. */
export function useCycleDirectory({ status, includeCompleted = true, excludeId = "", initialFilter = "", datedOnly = false, projectId = "" }: {
  status?: CycleStatusValue; includeCompleted?: boolean; excludeId?: string; initialFilter?: string;
  datedOnly?: boolean;
  /** RADD-1291: only cycles homed in, or holding issues of, this project. */
  projectId?: string;
} = {}) {
  return useDirectory(
    JSON.stringify(["cycles", status, includeCompleted, excludeId, datedOnly, projectId]),
    CYCLES_PAGE_SIZE,
    (q, page) => cyclesPageQuery(q, page, status, includeCompleted, excludeId, datedOnly, projectId),
    { initialFilter },
  );
}
