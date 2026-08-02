import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff } from "lucide-react";
import { api } from "../../lib/api";
import { apiPageWatchPath } from "../../lib/constants";
import { pageWatchQuery, queryKeys } from "../../lib/queries";

/**
 * Watch / unwatch a page (RADD-719).
 *
 * For a wiki that documents operations, a silently changed runbook is the
 * failure mode — the only way to know it moved was to reread it. Editing a page
 * auto-watches it (the server does that), so this button is for the people who
 * READ something and want to hear about it, which is the larger group.
 */
export function PageWatchButton({ pageId }: { pageId: string }) {
  const queryClient = useQueryClient();
  const { data } = useQuery(pageWatchQuery(pageId));
  const watching = data?.watching ?? false;

  const toggle = useMutation({
    mutationFn: () =>
      watching
        ? api.delete<{ watching: boolean }>(apiPageWatchPath(pageId))
        : api.put<{ watching: boolean }>(apiPageWatchPath(pageId), {}),
    onSettled: () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.pageWatch(pageId) }),
  });

  return (
    <button
      type="button"
      onClick={() => toggle.mutate()}
      title={watching ? "Stop watching this page" : "Watch this page for changes"}
      aria-label={watching ? "Stop watching this page" : "Watch this page"}
      aria-pressed={watching}
      className={
        "ml-1 rounded p-1 cursor-pointer hover:bg-elevated " +
        (watching ? "text-accent-text" : "text-fg-faint hover:text-fg")
      }
    >
      {watching ? <Bell size={13} aria-hidden /> : <BellOff size={13} aria-hidden />}
    </button>
  );
}
