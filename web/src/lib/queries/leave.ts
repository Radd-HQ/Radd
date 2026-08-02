/** Leave + team holidays: the app-wide on-leave indicator's one
 * cached query, the timesheet's range calendar, and the settings lists. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { ApiPath } from "../constants";
import type { CurrentLeave, LeaveCalendarEntry, LeavePeriod } from "../types";

/** Who is away TODAY. One query for every Avatar on screen — keep it calm. */
export const currentLeaveQuery = queryOptions({
  queryKey: ["leave", "current"] as const,
  queryFn: () => api.get<CurrentLeave[]>(ApiPath.leaveCurrent),
  staleTime: 5 * 60_000,
  refetchInterval: 5 * 60_000,
});

export const leaveCalendarQuery = (start: string, end: string) =>
  queryOptions({
    queryKey: ["leave", "calendar", start, end] as const,
    queryFn: () =>
      api.get<LeaveCalendarEntry[]>(ApiPath.leaveCalendar, { query: { start, end } }),
  });

export const myLeaveQuery = queryOptions({
  queryKey: ["leave", "mine"] as const,
  queryFn: () => api.get<LeavePeriod[]>(ApiPath.leaveMine),
});

export const holidaysQuery = queryOptions({
  queryKey: ["leave", "holidays"] as const,
  queryFn: () => api.get<LeavePeriod[]>(ApiPath.leaveHolidays),
});
