import type { QueryClient } from "@tanstack/react-query";
import { invalidatePluginData } from "@radd/plugin-sdk";

export type Kind = "leave" | "holiday";

/** `GET /leave/*` row. Times are wall clock in `timezone`; null = the whole day at that end. */
export interface Period {
  id: string;
  user_id: string | null;
  user_name?: string | null;
  team_id: string | null;
  team_name: string | null;
  kind: Kind;
  label: string;
  start_date: string;
  end_date: string;
  start_time?: string | null;
  end_time?: string | null;
  timezone?: string;
}
export interface TeamRef { id: string; name: string }
export interface TeamLeave {
  team_id: string;
  team_name: string;
  members: { id: string; name: string; timezone: string }[];
  periods: Period[];
}

/** Query-key root; `teams` (the /teams catalog) and `stewarded` (the teams the reader may
 *  record for) do not change when a period is written, so a write leaves them alone. */
export const LEAVE_QUERY = "leave";
const STABLE_KEYS = new Set(["teams", "stewarded"]);
/** A team section lists this many days back as well as everything current and upcoming. */
export const TEAM_LEAVE_LOOKBACK_DAYS = 30;

export function invalidateLeave(client: QueryClient): Promise<unknown> {
  return Promise.all([
    client.invalidateQueries({ queryKey: [LEAVE_QUERY], predicate: query => !STABLE_KEYS.has(String(query.queryKey[1])) }),
    invalidatePluginData(client, "leave"),
  ]);
}
