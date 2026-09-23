import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { CheckCheck, Inbox } from "lucide-react";
import { RoutePath } from "../lib/constants";
import { pagePermalink } from "../lib/page-links";
import {
  useMarkAllNotificationsRead,
  useMarkNotificationsRead,
} from "../lib/notify-mutations";
import { INBOX_PAGE_SIZE, notificationsQuery } from "../lib/queries";
import type { Notification } from "../lib/types";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { NotificationRow } from "../components/notifications/NotificationRow";
import { Pager } from "../components/Pager";
import { Spinner } from "../components/Spinner";
import { Switch } from "../components/Switch";
import { groupNotificationBursts } from "../lib/notification-bursts";

/** The personal notification Inbox (spec 26). */
export function InboxPage() {
  const [unreadOnly, setUnreadOnly] = useState(false);
  // RADD-884: the server pages; the page used to hard-cap at the first 100
  // and anything older was unreachable.
  const [page, setPage] = useState(1);
  const { data, isPending } = useQuery(notificationsQuery(unreadOnly, page));
  const markRead = useMarkNotificationsRead();
  const markAllRead = useMarkAllNotificationsRead();
  const navigate = useNavigate();

  const open = (notification: Notification) => {
    if (!notification.read) markRead.mutate([notification.id]);
    if (notification.item_key) {
      // RADD-1297: a comment notification opens ON the comment.
      const comment = notification.detail.comment_id;
      void navigate({
        to: RoutePath.issue,
        params: { itemKey: notification.item_key },
        ...(comment ? { search: { comment } } : {}),
      });
      return;
    }
    // RADD-1233: a page notification opens the page's permalink.
    const pageKey = notification.detail.page_number;
    if (pageKey) void navigate(pagePermalink(pageKey, notification.detail.comment_id));
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
        <Switch
          className="ml-auto"
          label="Unread only"
          checked={unreadOnly}
          onChange={(next) => {
            setUnreadOnly(next);
            setPage(1);
          }}
        />
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
        {groupNotificationBursts(data?.notifications ?? []).map((burst) => (
          <li key={burst.lead.id} data-burst={burst.members.length}>
            <NotificationRow
              notification={burst.lead}
              onOpen={(lead) => {
                // Opening a burst reads all of it: they are one fact.
                const unread = burst.members.filter((member) => !member.read).map((member) => member.id);
                if (unread.length > 1) markRead.mutate(unread);
                open(lead);
              }}
            />
            {burst.members.length > 1 && (
              <BurstMore burst={burst.members} onOpen={open} />
            )}
          </li>
        ))}
      </ul>
      {data && (page > 1 || data.notifications.length === INBOX_PAGE_SIZE) && (
        <div className="mt-3 flex justify-end">
          <Pager
            page={page}
            // No total from this endpoint: a short page means we're on the last one.
            pageCount={data.notifications.length < INBOX_PAGE_SIZE ? page : null}
            onPage={setPage}
          />
        </div>
      )}
    </div>
  );
}

/** "×14 — show all": the rest of a collapsed burst, on demand. */
function BurstMore({ burst, onOpen }: { burst: Notification[]; onOpen: (notification: Notification) => void }) {
  const [open, setOpen] = useState(false);
  const rest = burst.slice(1);
  return (
    <div className="px-4 pb-2 pl-11">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} data-burst-toggle
        className="text-xs text-fg-muted hover:text-fg hover:underline cursor-pointer">
        {open ? "Hide" : `${burst.length} times — show the other ${rest.length}`}
      </button>
      {open && (
        <ul className="mt-1 flex flex-col divide-y divide-subtle/50 rounded-md border border-subtle/60">
          {rest.map((notification) => (
            <li key={notification.id}>
              <NotificationRow notification={notification} onOpen={onOpen} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

