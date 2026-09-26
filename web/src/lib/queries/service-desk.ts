/** Service desk: canned responses + SLA policies (specs 30/63). The timers are the slas
 * plugin's remote (RADD-1394). */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import { ApiPath } from "../constants";
import { queryKeys } from "./shared";
import type { CannedResponse, SlaPolicy } from "../types";

/** Canned responses (spec 30) — readable by any member. */
export const cannedResponsesQuery = () =>
  queryOptions({
    queryKey: queryKeys.cannedResponses,
    queryFn: ({ signal }) => api.get<CannedResponse[]>(ApiPath.cannedResponses, { signal }),
    meta: entityMeta(Entity.cannedResponse),
  });

/** One project's SLA policies (spec 30; project-level since spec 67). */
export const slaPoliciesQuery = (projectId: string) =>
  queryOptions({
    queryKey: queryKeys.slaPolicies(projectId),
    queryFn: ({ signal }) =>
      api.get<SlaPolicy[]>(ApiPath.slaPolicies, { signal, query: { project_id: projectId } }),
    meta: entityMeta(Entity.slaPolicy),
  });
