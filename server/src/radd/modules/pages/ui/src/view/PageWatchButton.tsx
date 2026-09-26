import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff } from "lucide-react";
import { api, useIsAuthenticated } from "@radd/plugin-sdk";
import { pageWatchPath } from "../endpoints";
import { pageKeys, pageWatchQuery } from "../queries";

/** Watch / unwatch a page (RADD-719). Editing auto-watches server-side; this is for readers. */
export function PageWatchButton({ pageId }: { pageId: string }) {
  const queryClient = useQueryClient();
  const { data } = useQuery({ ...pageWatchQuery(pageId), enabled: useIsAuthenticated() });
  const watching = data?.watching ?? false;

  const toggle = useMutation({
    mutationFn: () =>
      watching
        ? api.delete<{ watching: boolean }>(pageWatchPath(pageId))
        : api.put<{ watching: boolean }>(pageWatchPath(pageId), {}),
    onSettled: () =>
      void queryClient.invalidateQueries({ queryKey: pageKeys.watch(pageId) }),
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
