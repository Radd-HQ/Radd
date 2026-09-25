/** Leave + team holidays: the app-wide on-leave indicator's one
 * cached query and the timesheet's range calendar. Settings lists live in the plugin UI. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { ApiPath } from "../constants";
import type { CurrentLeave, LeaveCalendarEntry } from "../types";

/** Who is away TODAY. One query for every Avatar on screen — keep it calm. */
export const currentLeaveQuery = queryOptions({
  queryKey: ["leave", "current"] as const,
  queryFn: ({ signal }) => api.get<CurrentLeave[]>(ApiPath.leaveCurrent, { signal }),
  staleTime: 5 * 60_000,
  refetchInterval: 5 * 60_000,
});

export const leaveCalendarQuery = (start: string, end: string) =>
  queryOptions({
    queryKey: ["leave", "calendar", start, end] as const,
    queryFn: ({ signal }) =>
      api.get<LeaveCalendarEntry[]>(ApiPath.leaveCalendar, { signal, query: { start, end } }),
  });
