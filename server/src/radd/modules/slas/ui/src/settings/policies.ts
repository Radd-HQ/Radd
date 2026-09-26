import { queryOptions } from "@tanstack/react-query";
import { api } from "@radd/plugin-sdk";
import type { PRIORITY_ORDER } from "@radd-plugin-ui/items/metadata";

/** The policy endpoints this plugin serves (`slas/router.py`). */
export const SLA_POLICIES_PATH = "/sla-policies";
export const slaPolicyPath = (policyId: string) => `${SLA_POLICIES_PATH}/${policyId}`;

/** The server's entity type for a policy (`slas.types.SlaEntity.POLICY`). Queries declare it
 *  verbatim, so realtime policy edits refresh them, and mutations invalidate by it. */
export const SLA_POLICY_ENTITY = "sla_policy";

/** The atom that manages a project's SLAs (RADD-1303: project-scoped, the Manager role's). */
export const SLA_UPDATE = "sla.update";

export type PriorityValue = (typeof PRIORITY_ORDER)[number];

/** RADD-1299 — what satisfies an SLA target (mirror of `slas.types.SlaMetOn`). */
export const SlaMetOn = {
  firstReply: "first_reply",
  replyByTeams: "reply_by_teams",
  replyByAssignedTeam: "reply_by_assigned_team",
  done: "done",
  entersStates: "enters_states",
  leavesStates: "leaves_states",
} as const;
export type SlaMetOnValue = (typeof SlaMetOn)[keyof typeof SlaMetOn];

/** One project's policy (project-level since spec 67; `PolicyRead`). */
export interface SlaPolicy {
  id: string;
  project_id: string;
  name: string;
  enabled: boolean;
  response_minutes: number | null;
  resolution_minutes: number | null;
  pause_state_names: string[];
  /** Count only the instance work week — weekends pause the clock (spec 35). */
  work_week_only: boolean;
  /** Spec 63: priorities the policy applies to; [] = every priority. */
  priorities: PriorityValue[];
  /** RADD-1043: issue type ids the policy applies to; [] = every type. */
  issue_type_ids: string[];
  /** Spec 63: first-match resolution order (position, then created_at). */
  position: number;
  /** Spec 63: daily business-hours window, minutes from midnight (both or neither). */
  business_start_minute: number | null;
  business_end_minute: number | null;
  /** Spec 69: emit sla.due_soon when remaining time drops to this (null = off). */
  warning_minutes: number | null;
  /** RADD-1299: applies only when the reporter is in one of these teams ([] = anyone). */
  reporter_team_ids: string[];
  /** RADD-1299: what satisfies each target, and the states/teams its mode names. */
  response_met_on: SlaMetOnValue;
  response_state_ids: string[];
  response_team_ids: string[];
  resolution_met_on: SlaMetOnValue;
  resolution_state_ids: string[];
  resolution_team_ids: string[];
  created_at: string;
  updated_at: string;
}

/** GET /issue-types?project_id= (itemtypes) — the fields a policy filter shows. */
interface IssueTypeChoice {
  id: string;
  name: string;
}

/** GET /states?project_id= (workflow) — what pause and "met when" rules pick from. */
export interface StateChoice {
  id: string;
  name: string;
}

/** One project's policies, in first-match order (server order: position, created_at). */
export const policiesQuery = (projectId: string) =>
  queryOptions({
    queryKey: ["slas", "policies", projectId] as const,
    queryFn: ({ signal }) => api.get<SlaPolicy[]>(SLA_POLICIES_PATH, { signal, query: { project_id: projectId } }),
    meta: { entities: [SLA_POLICY_ENTITY] },
  });

/** The project's issue types (a policy's type filter). */
export const issueTypesQuery = (projectId: string) =>
  queryOptions({
    queryKey: ["slas", "issue-types", projectId] as const,
    queryFn: ({ signal }) => api.get<IssueTypeChoice[]>("/issue-types", { signal, query: { project_id: projectId } }),
    staleTime: 60_000,
  });

/** The project's states — refreshed with the project's workflow (a state change tags `project`). */
export const statesQuery = (projectId: string) =>
  queryOptions({
    queryKey: ["slas", "states", projectId] as const,
    queryFn: ({ signal }) => api.get<StateChoice[]>("/states", { signal, query: { project_id: projectId } }),
    meta: { entities: ["project"], projectId },
    staleTime: 60_000,
  });
