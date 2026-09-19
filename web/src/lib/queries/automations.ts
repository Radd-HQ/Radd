/** Automation rules + the rule-builder catalog. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import {
  ApiPath,
  apiAutomationRunPath,
  apiAutomationRunsPath,
  apiAutomationVersionPath,
  apiAutomationVersionsPath,
} from "../constants";
import { queryKeys } from "./shared";
import {
  MANUAL_TRIGGER,
  SCHEDULE_TRIGGER,
  type AutomationCatalog,
  type AutomationRun,
  type AutomationRunDetail,
  type AutomationVersion,
  type AutomationVersionDetail,
  type EventSample,
  type Rule,
  type RunnableRule,
} from "../types";

// ---------------------------------------------------------------------------
// Automations + intake forms (spec 20). Automations need automation.manage;
// listing forms needs form.manage — both routes handle the 403.
// ---------------------------------------------------------------------------

/** Automation rules (spec 20) — requires automation.manage. */
export const automationsQuery = () =>
  queryOptions({
    queryKey: queryKeys.automations,
    queryFn: ({ signal }) => api.get<Rule[]>(ApiPath.automations, { signal }),
    retry: false,
  });

/** Trigger/subject/operator catalog for the rule builder (spec 58) — static per build. */
export const automationCatalogQuery = queryOptions({
  queryKey: queryKeys.automationCatalog,
  queryFn: ({ signal }) => api.get<AutomationCatalog>(`${ApiPath.automations}/catalog`, { signal }),
  staleTime: Infinity,
});

/** What an event type actually carries, sampled from real events (RADD-921).
 *
 * Per event type, cached for the session: the shape only changes when a module
 * starts emitting something new, and refetching on every trigger selection
 * would make clicking around the palette a stream of queries. */
export const eventSampleQuery = (eventType: string) =>
  queryOptions({
    queryKey: [...queryKeys.automationCatalog, "samples", eventType] as const,
    queryFn: ({ signal }) =>
      api.get<EventSample>(
        `${ApiPath.automations}/samples/events?event_type=${encodeURIComponent(eventType)}`, { signal },
      ),
    // A sentinel trigger (manual/schedule) is not an event and has no payload.
    enabled: Boolean(eventType) && eventType !== MANUAL_TRIGGER && eventType !== SCHEDULE_TRIGGER,
    staleTime: 5 * 60_000,
    retry: false,
  });

/** Enabled MANUAL rules, member-visible — the editor `/` menu's custom actions. */
export const runnableAutomationsQuery = () =>
  queryOptions({
    queryKey: [...queryKeys.automations, "runnable"] as const,
    queryFn: ({ signal }) => api.get<RunnableRule[]>(`${ApiPath.automations}/runnable`, { signal }),
    staleTime: 60_000,
    retry: false,
  });

/** Recorded runs of one automation, newest first (RADD-1266). Refetched on a
 * short interval while the panel is open, so a run that lands while someone is
 * watching appears without a reload. */
export const automationRunsQuery = (ruleId: string) =>
  queryOptions({
    queryKey: [...queryKeys.automations, ruleId, "runs"] as const,
    queryFn: ({ signal }) => api.get<AutomationRun[]>(apiAutomationRunsPath(ruleId), { signal }),
    refetchInterval: 15_000,
    retry: false,
  });

/** One run with its report. Immutable once written, so cached for the session. */
export const automationRunQuery = (ruleId: string, runId: string) =>
  queryOptions({
    queryKey: [...queryKeys.automations, ruleId, "runs", runId] as const,
    queryFn: ({ signal }) =>
      api.get<AutomationRunDetail>(apiAutomationRunPath(ruleId, runId), { signal }),
    staleTime: Infinity,
    retry: false,
  });

/** Every version of one automation, newest first (RADD-1268). */
export const automationVersionsQuery = (ruleId: string) =>
  queryOptions({
    queryKey: [...queryKeys.automations, ruleId, "versions"] as const,
    queryFn: ({ signal }) => api.get<AutomationVersion[]>(apiAutomationVersionsPath(ruleId), { signal }),
    retry: false,
  });

/** One version with its graph. Immutable, so cached for the session. */
export const automationVersionQuery = (ruleId: string, version: number) =>
  queryOptions({
    queryKey: [...queryKeys.automations, ruleId, "versions", version] as const,
    queryFn: ({ signal }) =>
      api.get<AutomationVersionDetail>(apiAutomationVersionPath(ruleId, version), { signal }),
    staleTime: Infinity,
    retry: false,
  });
