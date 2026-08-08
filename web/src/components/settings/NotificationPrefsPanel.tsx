import { Fragment } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { notificationPrefsQuery, queryKeys } from "../../lib/queries";
import {
  NotificationType,
  type NotificationPrefs,
  type NotificationTypeValue,
} from "../../lib/types";
import { ErrorText } from "../ErrorText";

/** Row order for the matrix — the labels' declaration order is the UI order. */
const NOTIFY_TYPE_LABELS: Record<NotificationTypeValue, string> = {
  [NotificationType.assigned]: "Assigned to me",
  [NotificationType.mentioned]: "Mentions",
  [NotificationType.participantAdded]: "Added as a participant",
  [NotificationType.stateChanged]: "State changes on watched issues",
  [NotificationType.commented]: "Comments on watched issues",
  [NotificationType.slaBreach]: "SLA breaches",
  [NotificationType.slaDueSoon]: "SLA due-soon warnings",
  [NotificationType.automation]: "Automation rules",
  [NotificationType.pageUpdated]: "Changes to pages I watch",
  [NotificationType.approval]: "Approval requests & decisions",
};

const NOTIFY_TYPES = Object.keys(NOTIFY_TYPE_LABELS) as NotificationTypeValue[];

/** Why the email box is disabled — the spec-96 posture: say it, don't just dim it. */
const EMAIL_NEEDS_INBOX =
  "Email needs the inbox on: a muted type never becomes a notification, so there is nothing to mail.";

/**
 * The per-type channel matrix (RADD-686): one row per notification type, one
 * checkbox per channel.
 *
 * Email requires inbox, and that is not a UI rule — a muted type never becomes
 * a notification row, and the mailer mails rows. So the email box is disabled
 * (and shows unchecked) while the inbox box is off, and muting a type here
 * drops it from `email_types` in the same request, mirroring the normalisation
 * the server applies. Otherwise re-enabling the inbox would resurrect an email
 * setting the server had already discarded.
 */
export function NotificationPrefsPanel() {
  const queryClient = useQueryClient();
  const prefs = useQuery(notificationPrefsQuery());
  const save = useMutation({
    mutationFn: (next: NotificationPrefs) =>
      api.put<NotificationPrefs>(ApiPath.notificationPrefs, next),
    onSuccess: (data) => queryClient.setQueryData(queryKeys.notificationPrefs, data),
  });

  if (prefs.isPending) return <p className="text-xs text-fg-faint">Loading preferences…</p>;
  if (prefs.isError)
    return <p className="text-xs text-red-400">Failed to load: {errorMessage(prefs.error)}</p>;

  const current = prefs.data;
  const muted = new Set(current.muted_types);
  const emailed = new Set(current.email_types);

  const put = (next: Partial<NotificationPrefs>) =>
    save.mutate({ ...current, ...next });

  const toggleInbox = (type: NotificationTypeValue) => {
    const nextMuted = new Set(muted);
    const nextEmailed = new Set(emailed);
    // `delete` is true when it WAS muted — that click un-mutes it. False means
    // it was on and is being muted, which also loses its email entry.
    if (!nextMuted.delete(type)) {
      nextMuted.add(type);
      nextEmailed.delete(type);
    }
    put({ muted_types: [...nextMuted], email_types: [...nextEmailed] });
  };

  const toggleEmail = (type: NotificationTypeValue) => {
    const nextEmailed = new Set(emailed);
    if (!nextEmailed.delete(type)) nextEmailed.add(type);
    put({ email_types: [...nextEmailed] });
  };

  return (
    <div className="flex max-w-md flex-col gap-3">
      <div className="grid grid-cols-[1fr_auto_auto] items-center gap-x-5 gap-y-2">
        <span />
        <span className="text-[11px] font-medium uppercase tracking-wide text-fg-muted">
          Inbox
        </span>
        <span className="text-[11px] font-medium uppercase tracking-wide text-fg-muted">
          Email
        </span>
        {NOTIFY_TYPES.map((type) => {
          const label = NOTIFY_TYPE_LABELS[type];
          const inInbox = !muted.has(type);
          return (
            <Fragment key={type}>
              <span className={"text-[13px] " + (inInbox ? "text-fg" : "text-fg-muted")}>
                {label}
              </span>
              <input
                type="checkbox"
                aria-label={`${label} — in my inbox`}
                checked={inInbox}
                onChange={() => toggleInbox(type)}
                disabled={save.isPending}
                className="size-3.5 justify-self-center accent-accent"
              />
              <input
                type="checkbox"
                aria-label={`${label} — by email`}
                checked={inInbox && emailed.has(type)}
                onChange={() => toggleEmail(type)}
                disabled={save.isPending || !inInbox}
                title={inInbox ? undefined : EMAIL_NEEDS_INBOX}
                className="size-3.5 justify-self-center accent-accent disabled:opacity-40"
              />
            </Fragment>
          );
        })}
      </div>
      <label className="flex items-center gap-2 border-t border-subtle pt-3 text-[13px] text-fg">
        <input
          type="checkbox"
          checked={current.email_digest}
          onChange={() => put({ email_digest: !current.email_digest })}
          disabled={save.isPending}
          className="size-3.5 accent-accent"
        />
        Email digest of unread notifications
      </label>
      {save.isError && <ErrorText error={save.error} />}
    </div>
  );
}
