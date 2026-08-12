import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { Button, ButtonVariant, ButtonSize } from "../../Button";
import { Select } from "../../Select";
import { useConfirm } from "../../ConfirmDialog";
import {
  pageSpacesQuery,
  projectsQuery,
  teamsQuery,
} from "../../../lib/queries";
import {
  Channel,
  NotificationType,
  RuleScope,
  type ChannelValue,
  type NotificationPrefs,
  type NotificationRule,
  type NotificationTypeValue,
  type RuleScopeValue,
} from "../../../lib/types";
import { ChannelCell } from "./ChannelCell";
import { SCOPE_HINTS, SCOPE_LABELS, SUBSCRIPTION_SCOPES, resolveSubscriptionCell, subscriptions } from "./matrix";

/**
 * Subscriptions: "tell me about everything in this project / space / team".
 *
 * The reach the whole spec exists for, and it needs no new machinery — a
 * subscription is a rule row with a target, and its per-kind cells are the same
 * control as the matrix above.
 *
 * **An unset cell here reads `off`, not your "Mine" value.** Your own columns
 * still outrank a subscription — for items you have a relationship WITH. A
 * subscription is for the ones you do not, and for those it is the only
 * applicable scope, so the resolver falls to the subscription scope's default,
 * which is `off`. Showing the "Mine" value would describe a notification that
 * never arrives.
 *
 * Only ambient kinds get a cell. A personal kind resolves through `own` alone
 * whatever scope you are looking at, so offering it here would be offering a
 * control that cannot do anything — the failure this codebase already fixed once
 * for un-writable fields (spec 96).
 */
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
    kind: NotificationTypeValue,
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
  const [target, setTarget] = useState("");
  const projects = useQuery(projectsQuery());
  const spaces = useQuery(pageSpacesQuery());
  const teams = useQuery(teamsQuery());

  const taken = new Set(
    prefs.rules.filter((r) => r.scope_id).map((r) => `${r.scope}:${r.scope_id}`),
  );
  const candidates: { value: string; label: string }[] =
    scope === RuleScope.project
      ? (projects.data ?? []).map((p) => ({ value: p.id, label: `${p.key} · ${p.name}` }))
      : scope === RuleScope.space
        ? (spaces.data ?? []).map((s) => ({ value: s.id, label: s.name }))
        : (teams.data ?? []).map((t) => ({ value: t.id, label: t.name }));
  const options = candidates.filter((option) => !taken.has(`${scope}:${option.value}`));
  const chosen = options.find((option) => option.value === target);

  return (
    <div className="flex flex-wrap items-end gap-2 border-t border-subtle pt-3">
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium text-fg-secondary">Subscribe to</span>
        <Select
          value={scope}
          onChange={(value) => {
            setScope(value as RuleScopeValue);
            setTarget("");
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
      <Select
        value={target}
        onChange={setTarget}
        className="w-64"
        aria-label="Subscription target"
        placeholder={options.length ? "Choose one…" : "Nothing left to subscribe to"}
        options={options}
      />
      <Button
        size={ButtonSize.sm}
        disabled={disabled || !chosen}
        onClick={() => {
          if (!chosen) return;
          onAdd(scope, chosen.value, chosen.label);
          setTarget("");
        }}
      >
        <Plus size={14} aria-hidden />
        Add
      </Button>
    </div>
  );
}

/**
 * A brand-new subscription starts with ONE kind switched on: the arrival of a
 * new thing in the place you just subscribed to.
 *
 * It has to start with something — an empty channel map is the same statement as
 * having no row, the server drops it on save, and a page that silently discards
 * what you just added is worse than one that guesses. But the guess was every
 * ambient kind, which is eight rows per click: subscribe to a busy project to
 * hear about new issues and you also asked for every comment, every state
 * change, every field edit, both SLA timers and the whole wiki. That is the
 * shape of a notification system people turn off.
 *
 * So: the kind a subscription is FOR, and the rest left at their `off` default,
 * one click each away. `page_created` for a space, `created` for a project or a
 * team — because they are different kinds and only one of them can ever fire for
 * a given scope. A space subscription seeded with `created` would be a row that
 * looks configured and delivers nothing (`created` is planned from item events,
 * which carry no space), which is the same class of lie the greyed personal
 * cells exist to avoid.
 */
export function seedChannels(
  scope: RuleScopeValue,
): Partial<Record<NotificationTypeValue, ChannelValue>> {
  const arrival =
    scope === RuleScope.space ? NotificationType.pageCreated : NotificationType.created;
  return { [arrival]: Channel.inbox };
}
