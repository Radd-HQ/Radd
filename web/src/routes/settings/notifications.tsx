import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { notificationPrefsQuery, queryKeys } from "../../lib/queries";
import {
  type ChannelValue,
  type NotificationPrefs,
  type NotificationRule,
  type NotificationTypeValue,
  type RuleScopeValue,
} from "../../lib/types";
import { ErrorText } from "../../components/ErrorText";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { NotificationMatrix } from "../../components/settings/notifications/NotificationMatrix";
import {
  SubscriptionList,
  seedChannels,
} from "../../components/settings/notifications/SubscriptionList";
import { toUpdate, withCell } from "../../components/settings/notifications/matrix";

/**
 * Settings → Notifications (spec 118).
 *
 * Two sections and a toggle: the defaults MATRIX (kind × relationship), the
 * SUBSCRIPTIONS that reach past your own work, and the digest.
 *
 * Every write is a full-replace PUT of the whole rule set, and the response is
 * written straight into the cache — so what the page shows after a save is what
 * the server stored, normalisation included, rather than what the click
 * intended. That distinction is the whole reason the old panel's two checkboxes
 * could quietly disagree with the row behind them.
 */
export function NotificationSettingsPage() {
  const queryClient = useQueryClient();
  const prefs = useQuery(notificationPrefsQuery());
  const save = useMutation({
    mutationFn: (body: ReturnType<typeof toUpdate>) =>
      api.put<NotificationPrefs>(ApiPath.notificationPrefs, body),
    onSuccess: (data) => queryClient.setQueryData(queryKeys.notificationPrefs, data),
  });

  return (
    <SettingsPage
      title="Notifications"
      description="What reaches you, and how. Every row is a kind of event; every column is how you are connected to it."
      info={
        <>
          <strong className="font-medium">Most specific wins.</strong> A cell you have not set
          shows what it inherits, dimmed — hover it to see where from. Your own work outranks
          things you follow, which outrank a team, which outrank a subscription; a subscription
          only overrides what it explicitly says.
        </>
      }
    >
      {prefs.isPending && <p className="text-xs text-fg-faint">Loading preferences…</p>}
      {prefs.isError && (
        <p className="text-xs text-red-400">Failed to load: {errorMessage(prefs.error)}</p>
      )}
      {prefs.data && (
        <Editor
          prefs={prefs.data}
          saving={save.isPending}
          error={save.error}
          onSave={(rules, digest) => save.mutate(toUpdate(rules, digest))}
        />
      )}
    </SettingsPage>
  );
}

function Editor({
  prefs,
  saving,
  error,
  onSave,
}: {
  prefs: NotificationPrefs;
  saving: boolean;
  error: unknown;
  onSave: (rules: NotificationRule[], emailDigest: boolean) => void;
}) {
  const setCell = (
    scope: RuleScopeValue,
    scopeId: string | null,
    kind: NotificationTypeValue,
    channel: ChannelValue | null,
  ) => onSave(withCell(prefs.rules, scope, scopeId, kind, channel), prefs.email_digest);

  return (
    <div className="flex max-w-3xl flex-col gap-8">
      <section>
        <h3 className="mb-1 text-sm font-semibold text-fg">Defaults</h3>
        <p className="mb-4 text-xs text-fg-muted">
          The bell means your inbox; the envelope means an email as it happens. They are
          independent — email with no inbox row is a real answer. Anything you are not emailed
          about individually can still arrive in the digest below.
        </p>
        <NotificationMatrix
          prefs={prefs}
          disabled={saving}
          onCell={(scope, kind, channel) => setCell(scope, null, kind, channel)}
        />
      </section>

      <section className="border-t border-subtle pt-6">
        <h3 className="mb-1 text-sm font-semibold text-fg">Subscriptions</h3>
        <p className="mb-4 text-xs text-fg-muted">
          Follow a whole project, wiki space or team — including work nobody has assigned to
          you or shared with you. A new subscription starts by telling you what arrives;
          anything you leave alone stays off here, while your defaults above keep applying
          to work you are actually part of.
        </p>
        <SubscriptionList
          prefs={prefs}
          disabled={saving}
          onCell={(rule, kind, channel) =>
            setCell(rule.scope, rule.scope_id, kind, channel)
          }
          onAdd={(scope, scopeId, label) =>
            onSave(
              [
                ...prefs.rules,
                {
                  scope,
                  scope_id: scopeId,
                  scope_label: label,
                  channels: seedChannels(scope),
                },
              ],
              prefs.email_digest,
            )
          }
          onRemove={(rule) =>
            onSave(
              prefs.rules.filter((row) => row !== rule),
              prefs.email_digest,
            )
          }
        />
      </section>

      <section className="border-t border-subtle pt-6">
        <h3 className="mb-1 text-sm font-semibold text-fg">Digest</h3>
        <p className="mb-3 text-xs text-fg-muted">
          A periodic email batching whatever reached your inbox and has not been emailed
          individually. Turning it off leaves those notifications in the inbox only.
        </p>
        <label className="flex items-center gap-2 text-[13px] text-fg">
          <input
            type="checkbox"
            checked={prefs.email_digest}
            onChange={() => onSave(prefs.rules, !prefs.email_digest)}
            disabled={saving}
            aria-label="Email digest of unread notifications"
            className="size-3.5 accent-accent"
          />
          Email digest of unread notifications
        </label>
      </section>

      {Boolean(error) && <ErrorText error={error} />}
    </div>
  );
}
