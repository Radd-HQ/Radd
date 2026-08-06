/** Automation rules + the rule-builder catalog. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import {
  ApiPath,
} from "../constants";
import { queryKeys } from "./shared";
import {
  MANUAL_TRIGGER,
  SCHEDULE_TRIGGER,
  type AutomationCatalog,
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
    queryFn: () => api.get<Rule[]>(ApiPath.automations),
    retry: false,
  });

/** Trigger/subject/operator catalog for the rule builder (spec 58) — static per build. */
export const automationCatalogQuery = queryOptions({
  queryKey: queryKeys.automationCatalog,
  queryFn: () => api.get<AutomationCatalog>(`${ApiPath.automations}/catalog`),
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
    queryFn: () =>
      api.get<EventSample>(
        `${ApiPath.automations}/samples/events?event_type=${encodeURIComponent(eventType)}`,
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
    queryFn: () => api.get<RunnableRule[]>(`${ApiPath.automations}/runnable`),
    staleTime: 60_000,
    retry: false,
  });
