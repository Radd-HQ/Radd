import { Fragment } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { notificationPrefsQuery, queryKeys } from "../../lib/queries";
import {
  Channel,
  RuleScope,
  type ChannelValue,
  type NotificationPrefs,
  type NotificationPrefsUpdate,
  type NotificationTypeValue,
} from "../../lib/types";
import { ErrorText } from "../ErrorText";

/** Why the email box is disabled — the spec-96 posture: say it, don't just dim it. */
const EMAIL_NEEDS_INBOX =
  "Email needs the inbox on here: this panel edits both relationship columns together.";

/** The two relationship columns this panel writes in lockstep (see below). */
const EDITED_SCOPES = [RuleScope.own, RuleScope.participating] as const;

function channelOf(inbox: boolean, email: boolean): ChannelValue {
  if (inbox && email) return Channel.both;
  if (inbox) return Channel.inbox;
  if (email) return Channel.email;
  return Channel.off;
}

/**
 * The per-kind channel matrix, on spec 118's scoped rules.
 *
 * **This panel is deliberately narrower than the model underneath it.** Spec
 * 118 gives every kind an answer per relationship (`own` / `participating` /
 * my-teams) plus per-subscription rules; a two-column grid on the Profile page
 * cannot express that, and pretending it could would let someone edit one
 * column and quietly disagree with two others. So it writes `own` and
 * `participating` TOGETHER — exactly the answer RADD-686 stored, which is what
 * makes it a faithful view of a matrix it does not fully show — and the
 * scope-aware editor lives on its own settings page.
 *
 * Rows, labels and inherited values all come from the server's vocabulary. The
 * panel used to hold its own `Record<NotificationType, string>`, so a kind added
 * on the server had no row here and nothing failed.
 */
export function NotificationPrefsPanel() {
  const queryClient = useQueryClient();
  const prefs = useQuery(notificationPrefsQuery());
  const save = useMutation({
    mutationFn: (next: NotificationPrefsUpdate) =>
      api.put<NotificationPrefs>(ApiPath.notificationPrefs, next),
    onSuccess: (data) => queryClient.setQueryData(queryKeys.notificationPrefs, data),
  });

  if (prefs.isPending) return <p className="text-xs text-fg-faint">Loading preferences…</p>;
  if (prefs.isError)
    return <p className="text-xs text-red-400">Failed to load: {errorMessage(prefs.error)}</p>;

  const current = prefs.data;
  // What each kind resolves to today for a personally-connected reader: the
  // saved `own` rule if there is one, otherwise the server's default for it.
  const ownRule = current.rules.find((rule) => rule.scope === RuleScope.own);
  const defaults = current.defaults[RuleScope.own] ?? {};
  const resolved = (kind: NotificationTypeValue): ChannelValue =>
    ownRule?.channels[kind] ?? defaults[kind] ?? Channel.off;

  const put = (channels: Partial<Record<NotificationTypeValue, ChannelValue>>, digest: boolean) => {
    // Everything this panel does not edit is preserved verbatim: subscriptions
    // and the my-teams column are somebody else's rows, and a full-replace PUT
    // that dropped them would delete a subscription as a side effect of ticking
    // a checkbox here.
    const untouched = current.rules.filter(
      (rule) => !(rule.scope_id === null && EDITED_SCOPES.some((s) => s === rule.scope)),
    );
    save.mutate({
      rules: [
        ...untouched.map((rule) => ({
          scope: rule.scope,
          scope_id: rule.scope_id,
          channels: rule.channels,
        })),
        ...EDITED_SCOPES.map((scope) => ({ scope, scope_id: null, channels })),
      ],
      email_digest: digest,
    });
  };

  const toggle = (kind: NotificationTypeValue, channel: "inbox" | "email") => {
    const channels: Partial<Record<NotificationTypeValue, ChannelValue>> = {};
    for (const spec of current.kinds) channels[spec.kind] = resolved(spec.kind);
    const now = resolved(kind);
    const inbox = now === Channel.inbox || now === Channel.both;
    const email = now === Channel.email || now === Channel.both;
    channels[kind] =
      channel === "inbox"
        ? // Turning the inbox off takes email with it, mirroring what this
          // panel's two boxes can express. The scope-aware page can say
          // "email only"; two checkboxes cannot show a third state.
          inbox
          ? Channel.off
          : channelOf(true, email)
        : channelOf(inbox, !email);
    put(channels, current.email_digest);
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
        {current.kinds.map((spec) => {
          const channel = resolved(spec.kind);
          const inInbox = channel === Channel.inbox || channel === Channel.both;
          const byEmail = channel === Channel.email || channel === Channel.both;
          return (
            <Fragment key={spec.kind}>
              <span
                className={"text-[13px] " + (inInbox ? "text-fg" : "text-fg-muted")}
                title={spec.description}
              >
                {spec.label}
              </span>
              <input
                type="checkbox"
                aria-label={`${spec.label} — in my inbox`}
                checked={inInbox}
                onChange={() => toggle(spec.kind, "inbox")}
                disabled={save.isPending}
                className="size-3.5 justify-self-center accent-accent"
              />
              <input
                type="checkbox"
                aria-label={`${spec.label} — by email`}
                checked={inInbox && byEmail}
                onChange={() => toggle(spec.kind, "email")}
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
          onChange={() => {
            const channels: Partial<Record<NotificationTypeValue, ChannelValue>> = {};
            for (const spec of current.kinds) channels[spec.kind] = resolved(spec.kind);
            put(channels, !current.email_digest);
          }}
          disabled={save.isPending}
          className="size-3.5 accent-accent"
        />
        Email digest of unread notifications
      </label>
      {save.isError && <ErrorText error={save.error} />}
    </div>
  );
}
