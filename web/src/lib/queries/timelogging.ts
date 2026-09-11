/** Time logging + timesheets (spec 22). */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import {
  ApiPath,
  apiItemTimelogPath,
  apiProjectTimeloggingPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  ItemTimeSummary,
  ProjectTimeLogging,
  Timesheet,
  WorkCategory,
} from "../types";

// ---------------------------------------------------------------------------
// Time logging + timesheets (spec 22)
// ---------------------------------------------------------------------------

/** Per-item time-tracking summary: estimate, logged, remaining + worklog entries. */
export const itemTimelogQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.itemTimelog(itemId),
    queryFn: ({ signal }) => api.get<ItemTimeSummary>(apiItemTimelogPath(itemId), { signal }),
  });

/** Shared work categories; `includeArchived` also returns archived ones (admin editor). */
export const workCategoriesQuery = (includeArchived = false) =>
  queryOptions({
    queryKey: queryKeys.workCategories(includeArchived),
    queryFn: ({ signal }) =>
      api.get<WorkCategory[]>(ApiPath.workCategories, {
        signal,
        query: { include_archived: includeArchived ? "true" : undefined },
      }),
    staleTime: 60_000,
  });

/** Whether time logging is enabled on a project (drives the issue-page panel). */
export const projectTimeloggingQuery = (projectId: string) =>
  queryOptions({
    queryKey: queryKeys.projectTimelogging(projectId),
    queryFn: ({ signal }) => api.get<ProjectTimeLogging>(apiProjectTimeloggingPath(projectId), { signal }),
    staleTime: 60_000,
  });

export interface TimesheetParams {
  start: string;
  end: string;
  userId?: string;
  teamId?: string;
  projectId?: string;
  /** Committed worklog SLQ (spec 98) — filtered SERVER-side, unlike the item
   *  pages' client-side intersection, because the timesheet's rows already come
   *  from one query and there is nothing to intersect against. */
  q?: string;
}

/** Timesheet entries for a window (spec 22) — the UI pivots them by day/person/issue. */
export const timesheetQuery = (params: TimesheetParams) =>
  queryOptions({
    queryKey: queryKeys.timesheet({
      start: params.start,
      end: params.end,
      userId: params.userId ?? "",
      teamId: params.teamId ?? "",
      projectId: params.projectId ?? "",
      q: params.q ?? "",
    }),
    queryFn: ({ signal }) =>
      api.get<Timesheet>(ApiPath.timesheet, {
        signal,
        query: {
          start: params.start,
          end: params.end,
          user_id: params.userId || undefined,
          team_id: params.teamId || undefined,
          project_id: params.projectId || undefined,
          q: params.q || undefined,
        },
      }),
  });
