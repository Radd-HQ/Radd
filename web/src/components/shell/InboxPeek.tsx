import { useEffect, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { CheckCheck, Inbox, X } from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { usePeek } from "../../lib/hooks";
import {
  useMarkAllNotificationsRead,
  useMarkNotificationsRead,
} from "../../lib/notify-mutations";
import { notificationsQuery } from "../../lib/queries";
import type { Notification } from "../../lib/types";
import { Button } from "../Button";
import { EmptyState } from "../EmptyState";
import { NotificationRow } from "../notifications/NotificationRow";
import { Spinner } from "../Spinner";

// Module-level open/toggle (the CommandPalette pattern): the bell button in
// the top bar and the drawer live in different trees, and threading state
// through the shell for one boolean isn't worth a context.
type Listener = () => void;
const toggleListeners = new Set<Listener>();
export function toggleInboxPeek() {
  for (const listener of toggleListeners) listener();
}

/**
 * The notifications PEEK: a right-side drawer over any surface (same bargain
 * as the issue peek — glance and triage without leaving the page). Opened
 * from the top-bar bell; a row click marks it read and opens the ISSUE peek
 * in place, so triage never navigates away. "Open inbox" is the full page.
 */
export function InboxPeek() {
  const [open, setOpen] = useState(false);
  const { data, isPending } = useQuery({ ...notificationsQuery(false), enabled: open });
  const markRead = useMarkNotificationsRead();
  const markAllRead = useMarkAllNotificationsRead();
  const peek = usePeek();

  useEffect(() => {
    const onToggle = () => setOpen((current) => !current);
    toggleListeners.add(onToggle);
    return () => {
      toggleListeners.delete(onToggle);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;

  const openNotification = (notification: Notification) => {
    if (!notification.read) markRead.mutate([notification.id]);
    if (notification.item_key) {
      // The issue peek takes over (it renders AFTER this drawer, so it would
      // paint on top anyway) — close the inbox so Esc/backdrop behave sanely.
      setOpen(false);
      peek.open(notification.item_key);
    }
  };

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/50 animate-fade-in"
        onClick={() => setOpen(false)}
        aria-hidden
      />
      <aside
        role="dialog"
        aria-label="Inbox"
        className="fixed inset-y-0 right-0 z-50 m-2 flex w-96 max-w-full animate-panel-in flex-col overflow-hidden rounded-2xl border border-subtle bg-base shadow-modal"
      >
        <div className="flex shrink-0 items-center gap-2 border-b border-subtle px-4 py-2.5">
          <h2 className="text-sm font-semibold text-heading">Inbox</h2>
          {data && data.unread_count > 0 && (
            <span className="rounded-full bg-accent/20 px-2 py-0.5 text-[11px] font-medium text-accent-text">
              {data.unread_count} new
            </span>
          )}
          <Button
            variant="secondary"
            size="sm"
            className="ml-auto"
            onClick={() => markAllRead.mutate()}
            disabled={!data || data.unread_count === 0}
          >
            <CheckCheck size={13} aria-hidden />
            Mark all read
          </Button>
          <button
            type="button"
            onClick={() => setOpen(false)}
            aria-label="Close inbox"
            className="rounded p-1 text-fg-secondary hover:bg-elevated hover:text-heading cursor-pointer"
          >
            <X size={15} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {isPending && <Spinner />}
          {data && data.notifications.length === 0 && (
            <div className="p-6">
              <EmptyState icon={Inbox} message="Nothing here — you're all caught up." />
            </div>
          )}
          <ul className="divide-y divide-subtle/70">
            {(data?.notifications ?? []).map((notification) => (
              <li key={notification.id}>
                <NotificationRow notification={notification} onOpen={openNotification} />
              </li>
            ))}
          </ul>
        </div>

        <div className="shrink-0 border-t border-subtle px-4 py-2">
          <Link
            to={RoutePath.inbox}
            onClick={() => setOpen(false)}
            className="text-xs text-fg-muted hover:text-accent-text"
          >
            Open inbox →
          </Link>
        </div>
      </aside>
    </>
  );
}
