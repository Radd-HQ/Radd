import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button, ButtonVariant, ButtonSize } from "../../Button";
import { Select } from "../../Select";
import { useConfirm } from "@radd/plugin-sdk";
import { SubscriptionTargetPicker } from "./SubscriptionTargetPicker";
import {
  Channel,
  NotificationType,
  RuleScope,
  type ChannelValue,
  type NotificationPrefs,
  type NotificationRule,
  type NotificationKindKey,
  type RuleScopeValue,
} from "../../../lib/types";
import { ChannelCell } from "./ChannelCell";
import { SCOPE_HINTS, SCOPE_LABELS, SUBSCRIPTION_SCOPES, resolveSubscriptionCell, subscriptions } from "./matrix";
import type { DirectoryOption } from "@radd/plugin-sdk";

/** Subscriptions: "tell me about everything in this project / space / team" —
 *  a rule row with a target, using the matrix's cell control. Unset cells read
 *  `off` (see `resolveSubscriptionCell`); only ambient kinds get a cell, since a
 *  personal kind resolves through `own` alone. */
export function SubscriptionList({
  prefs,
  disabled,
  onCell,
  onAdd,
  onRemove,
}: {
  prefs: NotificationPrefs;
  disabled: boolean;
  onCell: (
    rule: NotificationRule,
    kind: NotificationKindKey,
    channel: ChannelValue | null,
  ) => void;
  onAdd: (scope: RuleScopeValue, scopeId: string, label: string) => void;
  onRemove: (rule: NotificationRule) => void;
}) {
  const rows = subscriptions(prefs.rules);
  const ambient = prefs.kinds.filter((kind) => !kind.personal);
  const [confirmDialog, confirm] = useConfirm();

  return (
    <div className="flex flex-col gap-4">
      {confirmDialog}
      {rows.length === 0 && (
        <p className="text-[13px] text-fg-muted">
          No subscriptions. Add one to hear about everything in a project, a wiki space, or a
          team — including issues nobody has assigned to you.
        </p>
      )}
      {rows.map((rule) => (
        <div
          key={`${rule.scope}:${rule.scope_id}`}
          className="rounded-lg border border-subtle bg-surface p-3"
          data-subscription={rule.scope_id ?? undefined}
        >
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="min-w-0">
              {/* No label means the target is gone OR is no longer readable by
                  this account — the server refuses to name one it may not show
                  (notify/targets.py), and from here the two are the same fact. */}
              <span className="text-[13px] font-medium text-heading">
                {rule.scope_label ?? "(unavailable)"}
              </span>
              <span className="ml-2 rounded border border-subtle px-1.5 py-0.5 text-[11px] uppercase tracking-wide text-fg-muted">
                {SCOPE_LABELS[rule.scope]}
              </span>
              <p className="mt-0.5 text-[12px] leading-snug text-fg-muted">
                {SCOPE_HINTS[rule.scope]}
              </p>
            </div>
            <Button
              variant={ButtonVariant.ghost}
              size={ButtonSize.sm}
              disabled={disabled}
              onClick={async () => {
                const ok = await confirm({
                  title: `Remove this ${SCOPE_LABELS[rule.scope].toLowerCase()} subscription?`,
                  message: `You will stop hearing about ${rule.scope_label ?? "it"} unless you already watch something in it.`,
                  confirmLabel: "Remove",
                  danger: true,
                });
                if (ok) onRemove(rule);
              }}
            >
              <Trash2 size={14} aria-hidden />
              Remove
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
            {ambient.map((kind) => {
              const cell = resolveSubscriptionCell(prefs, rule, kind.kind);
              return (
                <span key={kind.kind} className="flex items-center gap-1.5">
                  <span className="text-[12px] text-fg-secondary">{kind.label}</span>
                  <ChannelCell
                    label={`${rule.scope_label ?? SCOPE_LABELS[rule.scope]} — ${kind.label}`}
                    resolved={cell.channel}
                    inheritedFrom={cell.inheritedFrom}
                    disabled={disabled}
                    onChange={(channel) => onCell(rule, kind.kind, channel)}
                  />
                </span>
              );
            })}
          </div>
        </div>
      ))}
      <AddSubscription prefs={prefs} disabled={disabled} onAdd={onAdd} />
    </div>
  );
}

/** Pick a project, space or team that is not already subscribed. */
function AddSubscription({
  prefs,
  disabled,
  onAdd,
}: {
  prefs: NotificationPrefs;
  disabled: boolean;
  onAdd: (scope: RuleScopeValue, scopeId: string, label: string) => void;
}) {
  const [scope, setScope] = useState<RuleScopeValue>(RuleScope.project);
  const [target, setTarget] = useState<DirectoryOption>();
  const [open, setOpen] = useState(false);
  const taken = new Set(prefs.rules.filter(row => row.scope === scope).map(row => row.scope_id));
  const chosen = target && !taken.has(target.value) ? target : undefined;

  return (
    <div className="flex flex-wrap items-end gap-2 border-t border-subtle pt-3">
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium text-fg-secondary">Subscribe to</span>
        <Select
          value={scope}
          onChange={(value) => {
            setScope(value as RuleScopeValue);
            setTarget(undefined);
          }}
          className="w-32"
          aria-label="Subscription kind"
          options={SUBSCRIPTION_SCOPES.map((option) => ({
            value: option,
            label: SCOPE_LABELS[option],
            title: SCOPE_HINTS[option],
          }))}
        />
      </label>
      <div className="flex min-w-0 basis-60 flex-col gap-1">
        <span className="text-xs font-medium text-fg-secondary">Subscription target</span>
        <Button variant="secondary" disabled={disabled} aria-label="Subscription target" aria-haspopup="dialog" onClick={() => setOpen(true)}>
          <span className="truncate">{chosen ? [scope === RuleScope.project ? chosen.hint : "", chosen.label].filter(Boolean).join(" · ") : "Choose one…"}</span>
        </Button>
      </div>
      {open && <SubscriptionTargetPicker scope={scope} onClose={() => setOpen(false)} onSelect={row => { setTarget(row); setOpen(false); }} />}
      <Button
        size={ButtonSize.sm}
        disabled={disabled || !chosen}
        onClick={() => {
          if (!chosen) return;
          onAdd(scope, chosen.value, [scope === RuleScope.project ? chosen.hint : "", chosen.label].filter(Boolean).join(" · "));
        }}
      >
        <Plus size={14} aria-hidden />
        Add
      </Button>
      <p className="basis-full text-[12px] leading-snug text-fg-muted">{SCOPE_HINTS[scope]}</p>
    </div>
  );
}

/** A new subscription starts with ONE kind on — the arrival of a new thing in
 *  that place (`page_created` for a space, `created` for a project/team). An
 *  empty map is dropped by the server; every ambient kind would be eight rows
 *  of noise; `created` on a space would never fire. */
export function seedChannels(
  scope: RuleScopeValue,
): Partial<Record<NotificationKindKey, ChannelValue>> {
  const arrival =
    scope === RuleScope.space ? NotificationType.pageCreated : NotificationType.created;
  return { [arrival]: Channel.inbox };
}
