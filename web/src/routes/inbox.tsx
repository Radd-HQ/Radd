import { useState, type ReactNode } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { CheckCheck, Inbox, Trash2, X } from "lucide-react";
import { RoutePath } from "../lib/constants";
import { pagePermalink } from "@radd-plugin-ui/pages/links";
import {
  useClearNotifications,
  useClearReadNotifications,
  useMarkAllNotificationsRead,
  useMarkNotificationsRead,
} from "../lib/notify-mutations";
import { pushToast, ToastKind } from "../lib/toast";
import { INBOX_PAGE_SIZE, notificationsQuery } from "../lib/queries";
import type { Notification } from "../lib/types";
import { Button } from "../components/Button";
import { EmptyState, IconButton, Switch, Pager, useConfirm } from "@radd/plugin-sdk";
import { NotificationRow } from "../components/notifications/NotificationRow";
import { Spinner } from "../components/Spinner";
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
  const clearRead = useClearReadNotifications();
  const clearOne = useClearNotifications();
  const clear = (ids: string[]) => clearOne.mutate(ids);
  const [confirmDialog, confirm] = useConfirm();
  const navigate = useNavigate();

  // Clearing deletes, so it asks first and says what stays (RADD-1568).
  const askToClear = async () => {
    const ok = await confirm({
      title: "Clear read notifications?",
      message: "Every notification you have read is removed from your inbox. Unread ones stay. This cannot be undone.",
      confirmLabel: "Clear read",
      danger: true,
    });
    if (!ok) return;
    clearRead.mutate(undefined, {
      onSuccess: ({ deleted }) => {
        setPage(1);
        pushToast(
          deleted === 0
            ? "Nothing to clear: no read notifications."
            : `Cleared ${deleted.toLocaleString()} read notification${deleted === 1 ? "" : "s"}.`,
          ToastKind.success,
        );
      },
    });
  };

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
    // RADD-1326: a plugin's kind names its own (site-relative) link.
    else if (notification.detail.link) window.location.assign(notification.detail.link);
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
        <Button
          variant="secondary"
          size="sm"
          data-clear-read
          onClick={() => void askToClear()}
          // Known to be pointless only when everything in view is unread.
          disabled={clearRead.isPending || !data || (!unreadOnly && page === 1 && data.notifications.every((n) => !n.read))}
        >
          <Trash2 size={13} aria-hidden />
          Clear read
        </Button>
      </div>

      {confirmDialog}
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
            <ClearableRow
              label={
                burst.members.length > 1
                  ? `Clear these ${burst.members.length} notifications`
                  : "Clear this notification"
              }
              // Clearing a folded row clears all of it, as opening it reads all of it.
              onClear={() => clear(burst.members.map((member) => member.id))}
            >
              <NotificationRow
                notification={burst.lead}
                onOpen={(lead) => {
                  // Opening a burst reads all of it: they are one fact.
                  const unread = burst.members.filter((member) => !member.read).map((member) => member.id);
                  if (unread.length > 1) markRead.mutate(unread);
                  open(lead);
                }}
              />
            </ClearableRow>
            {burst.members.length > 1 && (
              <BurstMore burst={burst.members} onOpen={open} onClear={(id) => clear([id])} />
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

/** A notification row with its clear button beside it (RADD-1569). Beside, not
 *  inside: the row is itself a button, and a button cannot hold another. No
 *  confirm: it is one row the person chose, and the list answers at once. */
function ClearableRow({ label, onClear, children }: { label: string; onClear: () => void; children: ReactNode }) {
  return (
    <div className="flex items-center">
      <div className="min-w-0 flex-1">{children}</div>
      <IconButton aria-label={label} title={label} data-clear-notification onClick={onClear} className="mr-2 shrink-0 p-1.5">
        <X size={14} aria-hidden />
      </IconButton>
    </div>
  );
}

/** "×14 — show all": the rest of a collapsed burst, on demand. */
function BurstMore({ burst, onOpen, onClear }: {
  burst: Notification[];
  onOpen: (notification: Notification) => void;
  onClear: (id: string) => void;
}) {
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
              <ClearableRow label="Clear this notification" onClear={() => onClear(notification.id)}>
                <NotificationRow notification={notification} onOpen={onOpen} />
              </ClearableRow>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

