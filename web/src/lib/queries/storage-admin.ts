/** Storage host registry + routing chain + move jobs (spec 102): Settings → Storage. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { ApiPath, apiStorageMoveJobPath } from "../constants";
import { queryKeys } from "./shared";
import type { MoveJobRead, StorageHostRead, StorageRuleRead, UploadContext } from "../types";

/** Configured storage hosts with usage counts. Secrets never leave the server. */
export const storageHostsQuery = () =>
  queryOptions({
    queryKey: queryKeys.storageHosts,
    queryFn: () => api.get<StorageHostRead[]>(ApiPath.storageHosts),
    staleTime: 30_000,
  });

/** The routing chain, position-ordered top-down. */
export const storageRulesQuery = () =>
  queryOptions({
    queryKey: queryKeys.storageRules,
    queryFn: () => api.get<StorageRuleRead[]>(ApiPath.storageRules),
    staleTime: 30_000,
  });

/** All move jobs — seeds the progress card when the page loads mid-move. */
export const storageMoveJobsQuery = () =>
  queryOptions({
    queryKey: queryKeys.storageMoveJobs,
    queryFn: () => api.get<MoveJobRead[]>(ApiPath.storageMoveJobs),
    staleTime: 10_000,
  });

/** One move job — the progress card polls this while pending/running. */
export const storageMoveJobQuery = (jobId: string) =>
  queryOptions({
    queryKey: queryKeys.storageMoveJob(jobId),
    queryFn: () => api.get<MoveJobRead>(apiStorageMoveJobPath(jobId)),
  });

/** Pre-upload context — the one NON-admin read here: any authenticated user
 * asks whether to pop the storage prompt. Cached ~30s so a burst of gestures
 * shares one probe. */
export const uploadContextQuery = (contentTypes: string[] = []) => {
  // Sorted-unique so "png then pdf" and "pdf then png" share a cache entry.
  const types = [...new Set(contentTypes)].sort();
  const qs = types.map((t) => `content_type=${encodeURIComponent(t)}`).join("&");
  return queryOptions({
    queryKey: [...queryKeys.storageUploadContext, types],
    queryFn: () =>
      api.get<UploadContext>(qs ? `${ApiPath.storageUploadContext}?${qs}` : ApiPath.storageUploadContext),
    staleTime: 30_000,
  });
};
