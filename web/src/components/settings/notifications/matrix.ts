/**
 * Reading and editing one person's notification matrix (spec 118).
 *
 * Pure functions over the wire shape, mirroring `notify/rules.py` on the client
 * side — NOT a second copy of the resolver. The server resolves for DELIVERY;
 * this resolves for DISPLAY, and the two answer different questions: delivery
 * knows which relation produced a given event, and a settings page is looking at
 * a column with no event in front of it. So this is the simpler half — one
 * scope, its own rule or the server's default — and the defaults themselves come
 * down the wire so the SPA never carries that table.
 */

import { Channel, RuleScope, type ChannelValue, type NotificationPrefs, type NotificationRule, type NotificationTypeValue, type RuleScopeValue } from "../../../lib/types";

/** What one relationship column shows for one kind, and where it came from. */
export interface ResolvedCell {
  channel: ChannelValue;
  /** Null when the person set this cell; otherwise the human name of the source. */
  inheritedFrom: string | null;
}

export const SCOPE_LABELS: Record<RuleScopeValue, string> = {
  [RuleScope.own]: "Mine",
  [RuleScope.participating]: "Following",
  [RuleScope.teams]: "My teams",
  [RuleScope.project]: "Project",
  [RuleScope.space]: "Space",
  [RuleScope.team]: "Team",
};

export const SCOPE_HINTS: Record<RuleScopeValue, string> = {
  [RuleScope.own]: "Issues assigned to you or that you reported.",
  [RuleScope.participating]:
    "Anything you watch, were shared into, or were named in — issues and pages.",
  [RuleScope.teams]: "Issues filed against a team you belong to.",
  [RuleScope.project]: "Everything in this project.",
  [RuleScope.space]: "Everything in this wiki space.",
  [RuleScope.team]: "Everything filed against this team.",
};

/** Personal kinds are addressed AT you, so only the first column can answer. */
export const PERSONAL_ONLY_REASON =
  "This one is addressed at you personally, so it always follows the “Mine” column.";

export function findRule(
  rules: NotificationRule[],
  scope: RuleScopeValue,
  scopeId: string | null = null,
): NotificationRule | undefined {
  return rules.find((rule) => rule.scope === scope && rule.scope_id === scopeId);
}

/** What a relationship cell resolves to, and whether it was inherited. */
export function resolveCell(
  prefs: NotificationPrefs,
  scope: RuleScopeValue,
  kind: NotificationTypeValue,
): ResolvedCell {
  const saved = findRule(prefs.rules, scope)?.channels[kind];
  if (saved) return { channel: saved, inheritedFrom: null };
  return {
    channel: prefs.defaults[scope]?.[kind] ?? Channel.off,
    inheritedFrom: "the default",
  };
}

/**
 * A subscription cell. Unset resolves to the SUBSCRIPTION scope's own default,
 * which is `off`.
 *
 * It is tempting to show the "Mine" value here, on the reasoning that a
 * relationship outranks a subscription so your own columns still apply. They do
 * — to items you have a relationship WITH. A subscription exists for the ones
 * you do not: for those, the subscription is the only applicable scope, so the
 * resolver falls to `DEFAULT_MATRIX[project|space|team]` and delivers nothing.
 * Showing "both, inherited from Mine" on a cell that delivers nothing is a
 * settings page describing a notification that never arrives, which is worse
 * than showing `off` — the person turns the feature off looking for the noise.
 *
 * The default comes from the server (`prefs.defaults` carries every scope, not
 * just the three columns), so this stays a lookup rather than a second copy of
 * the table.
 */
export function resolveSubscriptionCell(
  prefs: NotificationPrefs,
  rule: NotificationRule,
  kind: NotificationTypeValue,
): ResolvedCell {
  const saved = rule.channels[kind];
  if (saved) return { channel: saved, inheritedFrom: null };
  return {
    channel: prefs.defaults[rule.scope]?.[kind] ?? Channel.off,
    inheritedFrom: "the default",
  };
}

/** Replace one cell, returning the whole rule set for the full-replace PUT. */
export function withCell(
  rules: NotificationRule[],
  scope: RuleScopeValue,
  scopeId: string | null,
  kind: NotificationTypeValue,
  channel: ChannelValue | null,
): NotificationRule[] {
  const existing = findRule(rules, scope, scopeId);
  const channels = { ...(existing?.channels ?? {}) };
  if (channel === null) delete channels[kind];
  else channels[kind] = channel;
  const others = rules.filter((rule) => rule !== existing);
  // An empty channel map is the same statement as having no row — the server
  // drops it on save, so dropping it here keeps the page showing what was
  // stored rather than a row that will vanish on the next read.
  if (Object.keys(channels).length === 0) return others;
  const next: NotificationRule = {
    scope,
    scope_id: scopeId,
    scope_label: existing?.scope_label ?? null,
    channels,
  };
  return [...others, next];
}

/** The PUT body — `scope_label` is a read-only display value. */
export function toUpdate(rules: NotificationRule[], emailDigest: boolean) {
  return {
    rules: rules.map((rule) => ({
      scope: rule.scope,
      scope_id: rule.scope_id,
      channels: rule.channels,
    })),
    email_digest: emailDigest,
  };
}

/** Subscription rows only, grouped so the page lists projects, then spaces, then teams. */
export const SUBSCRIPTION_SCOPES: RuleScopeValue[] = [
  RuleScope.project,
  RuleScope.space,
  RuleScope.team,
];

export function subscriptions(rules: NotificationRule[]): NotificationRule[] {
  return rules
    .filter((rule) => rule.scope_id !== null)
    .sort(
      (a, b) =>
        SUBSCRIPTION_SCOPES.indexOf(a.scope) - SUBSCRIPTION_SCOPES.indexOf(b.scope) ||
        (a.scope_label ?? "").localeCompare(b.scope_label ?? ""),
    );
}
