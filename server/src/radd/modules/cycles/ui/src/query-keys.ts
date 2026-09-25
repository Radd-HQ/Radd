import type { CycleStatusValue } from "./types";
export const cycleDirectoryKeys = {
  cyclesPage: (q: string, page: number, status: CycleStatusValue | undefined, includeCompleted: boolean, excludeId: string, datedOnly: boolean, projectId = "") =>
    ["cycles", "page", { q, page, status, includeCompleted, excludeId, datedOnly, projectId }] as const,
  cycle: (cycleId: string) => ["cycle", { cycleId }] as const,
};
