import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { CheckCheck, Inbox } from "lucide-react";
import { RoutePath } from "../lib/constants";
import {
  useMarkAllNotificationsRead,
  useMarkNotificationsRead,
} from "../lib/notify-mutations";
import { notificationsQuery } from "../lib/queries";
import type { Notification } from "../lib/types";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { NotificationRow } from "../components/notifications/NotificationRow";
import { Spinner } from "../components/Spinner";

/** The personal notification Inbox (spec 26). */
export function InboxPage() {
  const [unreadOnly, setUnreadOnly] = useState(false);
  const { data, isPending } = useQuery(notificationsQuery(unreadOnly));
  const markRead = useMarkNotificationsRead();
  const markAllRead = useMarkAllNotificationsRead();
  const navigate = useNavigate();

  const open = (notification: Notification) => {
    if (!notification.read) markRead.mutate([notification.id]);
    if (notification.item_key) {
      void navigate({ to: RoutePath.issue, params: { itemKey: notification.item_key } });
    }
  };

  return (
    <div className="w-full px-6 py-6">
      <div className="mb-4 flex items-center gap-3">
        <h1 className="text-lg font-semibold text-heading">Inbox</h1>
        {data && data.unread_count > 0 && (
          <span className="rounded-full bg-accent/20 px-2 py-0.5 text-xs font-medium text-accent-text">
            {data.unread_count} unread
          </span>
        )}
        <label className="ml-auto flex items-center gap-1.5 text-xs text-fg-secondary">
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(event) => setUnreadOnly(event.target.checked)}
            className="accent-accent"
          />
          Unread only
        </label>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => markAllRead.mutate()}
          disabled={!data || data.unread_count === 0}
        >
          <CheckCheck size={13} aria-hidden />
          Mark all read
        </Button>
      </div>

      {isPending && <Spinner />}
      {data && data.notifications.length === 0 && (
        <EmptyState
          icon={Inbox}
          message={
            unreadOnly
              ? "No unread notifications."
              : "Assignments, @mentions, and activity on issues you watch land here."
          }
        />
      )}

      <ul className="divide-y divide-subtle/70 overflow-hidden rounded-lg border border-subtle">
        {(data?.notifications ?? []).map((notification) => (
          <li key={notification.id}>
            <NotificationRow notification={notification} onOpen={open} />
          </li>
        ))}
      </ul>
    </div>
  );
}
