/** Approval requests (spec 71). */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import { ApiPath } from "../constants";
import { queryKeys } from "./shared";
import type { PendingApproval } from "../types";

/** Requests awaiting MY verdict (spec 71) — the My Work card. */
export const pendingApprovalsQuery = queryOptions({
  queryKey: queryKeys.pendingApprovals,
  queryFn: ({ signal }) => api.get<PendingApproval[]>(ApiPath.approvalsPending, { signal }),
  meta: entityMeta(Entity.item),
});
