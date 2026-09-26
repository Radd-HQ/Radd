import type { QueryClient } from "@tanstack/react-query";
import { api, invalidatePluginCommands } from "@radd/plugin-sdk";
import {
  ApiPath,
  apiAutomationRunPath,
  apiAutomationRunsPath,
  apiAutomationVersionPath,
  apiAutomationVersionsPath,
} from "./constants";
const queryKeys = {automations: ["automations"] as const, automationCatalog: ["automations", "catalog"] as const};
import { isSentinelTrigger } from "./meta";
import {
  type AutomationCatalog,
  type AutomationTemplate,
  type AutomationRun,
  type AutomationRunDetail,
  type AutomationVersion,
  type AutomationVersionDetail,
  type EventSample,
  type Rule,
} from "./types";

/** Automation rules (spec 20) — requires automation.manage. */
export const automationsQuery = () =>
  ({
    queryKey: queryKeys.automations,
    queryFn: ({ signal }: {signal: AbortSignal}) => api.get<Rule[]>(ApiPath.automations, { signal }),
    retry: false,
  });

/** Whole-automation templates (RADD-1316) — refreshed with the loaded plugin set. */
export const automationTemplatesQuery = ({
  queryKey: [...queryKeys.automationCatalog, "templates"] as const,
  queryFn: ({ signal }: {signal: AbortSignal}) => api.get<AutomationTemplate[]>(`${ApiPath.automations}/templates`, { signal }),
  staleTime: Infinity,
});

/** Trigger/subject/operator catalog for the rule builder (spec 58) — refreshed with the loaded plugin set. */
export const automationCatalogQuery = ({
  queryKey: queryKeys.automationCatalog,
  queryFn: ({ signal }: {signal: AbortSignal}) => api.get<AutomationCatalog>(`${ApiPath.automations}/catalog`, { signal }),
  staleTime: Infinity,
});

/** What an event type carries, cached per type for the session. */
export const eventSampleQuery = (eventType: string) =>
  ({
    queryKey: [...queryKeys.automationCatalog, "samples", eventType] as const,
    queryFn: ({ signal }: {signal: AbortSignal}) =>
      api.get<EventSample>(
        `${ApiPath.automations}/samples/events?event_type=${encodeURIComponent(eventType)}`, { signal },
      ),
    enabled: Boolean(eventType) && !isSentinelTrigger(eventType),
    staleTime: 5 * 60_000,
    retry: false,
  });

/** Recorded runs of one automation, newest first (RADD-1266). Refetched on a
 * short interval while the panel is open, so a run that lands while someone is
 * watching appears without a reload. */
export const automationRunsQuery = (ruleId: string) =>
  ({
    queryKey: [...queryKeys.automations, ruleId, "runs"] as const,
    queryFn: ({ signal }: {signal: AbortSignal}) => api.get<AutomationRun[]>(apiAutomationRunsPath(ruleId), { signal }),
    refetchInterval: 15_000,
    retry: false,
  });

/** One run with its report. Immutable once written, so cached for the session. */
export const automationRunQuery = (ruleId: string, runId: string) =>
  ({
    queryKey: [...queryKeys.automations, ruleId, "runs", runId] as const,
    queryFn: ({ signal }: {signal: AbortSignal}) =>
      api.get<AutomationRunDetail>(apiAutomationRunPath(ruleId, runId), { signal }),
    staleTime: Infinity,
    retry: false,
  });

/** Every version of one automation, newest first (RADD-1268). */
export const automationVersionsQuery = (ruleId: string) =>
  ({
    queryKey: [...queryKeys.automations, ruleId, "versions"] as const,
    queryFn: ({ signal }: {signal: AbortSignal}) => api.get<AutomationVersion[]>(apiAutomationVersionsPath(ruleId), { signal }),
    retry: false,
  });

/** One version with its graph. Immutable, so cached for the session. */
export const automationVersionQuery = (ruleId: string, version: number) =>
  ({
    queryKey: [...queryKeys.automations, ruleId, "versions", version] as const,
    queryFn: ({ signal }: {signal: AbortSignal}) =>
      api.get<AutomationVersionDetail>(apiAutomationVersionPath(ruleId, version), { signal }),
    staleTime: Infinity,
    retry: false,
  });

export function invalidateAutomations(client: QueryClient) {
  return Promise.all([client.invalidateQueries({queryKey: queryKeys.automations}), invalidatePluginCommands(client, "automations")]);
}
