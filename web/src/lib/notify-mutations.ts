import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { Entity, invalidateEntities } from "@radd/plugin-sdk";
import {
  apiItemWatchPath,
  apiNotificationsClearPath,
  apiNotificationsReadAllPath,
  apiNotificationsReadPath,
} from "./constants";

/** Mark specific notifications read (Inbox row click). */
export function useMarkNotificationsRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[]) => api.post<void>(apiNotificationsReadPath(), { ids }),
    onSettled: () => invalidateEntities(queryClient, Entity.notification),
  });
}

export function useMarkAllNotificationsRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>(apiNotificationsReadAllPath()),
    onSettled: () => invalidateEntities(queryClient, Entity.notification),
  });
}

/** Delete these notifications: one row, or every member of a folded burst (RADD-1569). */
export function useClearNotifications() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[]) => api.post<{ deleted: number }>(apiNotificationsClearPath(), { ids }),
    onSettled: () => invalidateEntities(queryClient, Entity.notification),
  });
}

/** Delete the caller's read notifications (RADD-1568); resolves to how many went. */
export function useClearReadNotifications() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.delete<{ deleted: number }>(apiNotificationsReadPath()),
    onSettled: () => invalidateEntities(queryClient, Entity.notification),
  });
}

/** Follow/unfollow an item (manual watch, spec 26). */
export function useToggleWatch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ itemId, watch }: { itemId: string; watch: boolean }) => {
      if (watch) await api.put<void>(apiItemWatchPath(itemId));
      else await api.delete<void>(apiItemWatchPath(itemId));
    },
    onSettled: () => invalidateEntities(queryClient, Entity.watcher),
  });
}
