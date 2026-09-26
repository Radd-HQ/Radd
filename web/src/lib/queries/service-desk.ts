/** Service desk: canned responses (spec 30). SLA policies, timers and queues are the slas
 * plugin's (RADD-1394/1396). */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import { ApiPath } from "../constants";
import { queryKeys } from "./shared";
import type { CannedResponse } from "../types";

/** Canned responses (spec 30) — readable by any member. */
export const cannedResponsesQuery = () =>
  queryOptions({
    queryKey: queryKeys.cannedResponses,
    queryFn: ({ signal }) => api.get<CannedResponse[]>(ApiPath.cannedResponses, { signal }),
    meta: entityMeta(Entity.cannedResponse),
  });
