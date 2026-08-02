import { useQuery } from "@tanstack/react-query";
import { Bell, BellOff } from "lucide-react";
import { useToggleWatch } from "../../lib/notify-mutations";
import { itemWatchersQuery } from "../../lib/queries";
import type { Item } from "../../lib/types";

/**
 * Follow/unfollow toggle on the issue-detail header (spec 26). Watchers get
 * notified on state changes and comments; assignment/comment/create auto-watch,
 * this is the manual override. Shows the watcher count when anyone follows.
 */
export function WatchButton({ item }: { item: Item }) {
  const { data } = useQuery(itemWatchersQuery(item.id));
  const toggleWatch = useToggleWatch();
  const watching = data?.watching ?? false;
  const count = data?.watchers.length ?? 0;
  const names = data?.watchers.map((watcher) => watcher.name).join(", ");

  return (
    <button
      type="button"
      onClick={() => toggleWatch.mutate({ itemId: item.id, watch: !watching })}
      aria-pressed={watching}
      title={
        (watching ? "Watching — you get notified of changes." : "Watch this issue.") +
        (names ? ` Watchers: ${names}` : "")
      }
      className={
        "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs cursor-pointer " +
        (watching
          ? "border-accent-hover/50 bg-accent-hover/10 text-accent-text-strong"
          : "border-strong text-fg-secondary hover:text-fg hover:border-emphasis")
      }
    >
      {watching ? <Bell size={13} aria-hidden /> : <BellOff size={13} aria-hidden />}
      {watching ? "Watching" : "Watch"}
      {count > 0 && <span className="text-[10px] text-fg-muted">{count}</span>}
    </button>
  );
}
