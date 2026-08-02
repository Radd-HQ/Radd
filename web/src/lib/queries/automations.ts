/** Automation rules + the rule-builder catalog. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import {
  ApiPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  AutomationCatalog,
  Rule,
  RunnableRule,
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

/** Enabled MANUAL rules, member-visible — the editor `/` menu's custom actions. */
export const runnableAutomationsQuery = () =>
  queryOptions({
    queryKey: [...queryKeys.automations, "runnable"] as const,
    queryFn: () => api.get<RunnableRule[]>(`${ApiPath.automations}/runnable`),
    staleTime: 60_000,
    retry: false,
  });
