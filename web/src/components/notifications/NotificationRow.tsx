import {
  AlarmClock,
  AtSign,
  CircleDot,
  FileText,
  MessageSquare,
  ShieldCheck,
  Timer,
  UserRoundPlus,
  Users,
  Zap,
} from "lucide-react";
import { shortDate } from "../../lib/dates";
import { NotificationType, type Notification } from "../../lib/types";

/** One-line, human sentence for a notification row (actor + verb). */
export function notificationSummary(notification: Notification): string {
  const actor = notification.actor?.name ?? "Someone";
  switch (notification.type) {
    case NotificationType.assigned:
      return `${actor} assigned you`;
    case NotificationType.mentioned:
      return `${actor} mentioned you`;
    case NotificationType.stateChanged:
      return `${actor} moved ${notification.detail.from ?? "?"} → ${notification.detail.to ?? "?"}`;
    case NotificationType.slaBreach:
      return `SLA ${notification.detail.kind ?? ""} target breached (${notification.detail.policy ?? "policy"})`;
    case NotificationType.slaDueSoon:
      return `SLA ${notification.detail.kind ?? ""} target due soon (${notification.detail.policy ?? "policy"})`;
    case NotificationType.automation:
      return String(notification.detail.message ?? `Rule "${notification.detail.rule ?? "?"}" fired`);
    case NotificationType.approval: {
      const target = notification.detail.to_state ?? "?";
      switch (notification.detail.action) {
        case "approved":
          return `${actor} approved the move to ${target}`;
        case "declined":
          return `${actor} declined the move to ${target}`;
        default:
          return `${actor} requested your approval to move to ${target}`;
      }
    }
    case NotificationType.pageUpdated:
      return `${actor} edited ${notification.detail.title ?? "a page"}`;
    // RADD-978. "…as a participant" rather than the email's "…to the issue":
    // the row appends " on KEY" itself, so this is the phrasing that survives
    // it. It needs its own case at all because the fallback below claims
    // someone commented — the bug RADD-967 fixed on the server side.
    case NotificationType.participantAdded:
      return `${actor} added you as a participant`;
    default:
      return `${actor} commented`;
  }
}

const TYPE_ICONS = {
  [NotificationType.assigned]: UserRoundPlus,
  [NotificationType.mentioned]: AtSign,
  [NotificationType.stateChanged]: CircleDot,
  [NotificationType.commented]: MessageSquare,
  [NotificationType.slaBreach]: Timer,
  [NotificationType.slaDueSoon]: AlarmClock,
  [NotificationType.automation]: Zap,
  [NotificationType.approval]: ShieldCheck,
  [NotificationType.pageUpdated]: FileText,
  [NotificationType.participantAdded]: Users,
} as const;

/** One notification row (shared by the Inbox page and the top-bar peek). */
export function NotificationRow({
  notification,
  onOpen,
}: {
  notification: Notification;
  onOpen: (notification: Notification) => void;
}) {
  const Icon = TYPE_ICONS[notification.type] ?? MessageSquare;
  return (
    <button
      type="button"
      onClick={() => onOpen(notification)}
      className={
        "flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-elevated/50 cursor-pointer " +
        (notification.read ? "opacity-60" : "")
      }
    >
      <span className="mt-0.5 shrink-0 text-fg-muted">
        <Icon size={15} aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] text-fg">
          {notificationSummary(notification)}
          {notification.item_key && (
            <>
              {" on "}
              <span className="font-mono text-xs text-fg-secondary">
                {notification.item_key}
              </span>
            </>
          )}
        </span>
        {notification.item_title && (
          <span className="block truncate text-xs text-fg-muted">
            {notification.item_title}
          </span>
        )}
        {notification.detail.excerpt && (
          <span className="mt-1 block truncate rounded bg-elevated/60 px-2 py-1 text-xs italic text-fg-secondary">
            “{notification.detail.excerpt}”
          </span>
        )}
      </span>
      <span className="flex shrink-0 flex-col items-end gap-1">
        <time
          className="text-[11px] text-fg-faint"
          dateTime={notification.created_at}
          title={new Date(notification.created_at).toLocaleString()}
        >
          {shortDate(notification.created_at)}
        </time>
        {!notification.read && (
          <span className="size-2 rounded-full bg-accent-hover" aria-label="Unread" />
        )}
      </span>
    </button>
  );
}
