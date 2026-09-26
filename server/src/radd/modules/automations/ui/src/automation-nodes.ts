/** The node catalogue behind both the panel and the right-click menu, built from the served catalog. */
import { defaultsFromSchema } from "@radd/plugin-sdk";
import {
  NodeArity,
  NodeKind,
  type AutomationCatalog,
  type AutomationNode,
  type NodeKindValue,
} from "./types";
import { isProducer, suggestNodeName } from "./automation-outputs";

export interface NodeTemplate {
  /** Stable key, used as the search value and the React key. */
  key: string;
  kind: NodeKindValue;
  /** The stored node `type`. */
  type: string;
  label: string;
  /** Section heading in the panel — "Triggers · Items", "Actions", … */
  group: string;
  /** Extra words the search should match (event type, synonyms). */
  keywords: string;
  params: Record<string, unknown>;
  /** Whether a node of this type produces named values (spec 120), so a fresh
   * one should arrive with a suggested NAME. Computed where the catalog is in
   * scope; `instantiate` only has the template. */
  produces?: boolean;
}

const TRIGGER_GROUP = "Triggers";

/** Static ports by node type (terminal = none); params-dependent types are absent. */
export function contributedPorts(
  catalog: AutomationCatalog | undefined,
): Record<string, string[]> {
  const map: Record<string, string[]> = {};
  for (const node of catalog?.nodes ?? []) {
    if (node.ports?.length || node.terminal) map[node.key] = node.terminal ? [] : node.ports;
  }
  return map;
}

export function nodeTemplates(catalog: AutomationCatalog | undefined): NodeTemplate[] {
  const templates: NodeTemplate[] = [];

  // --- triggers, grouped the way the server groups its events ---
  for (const trigger of catalog?.triggers ?? []) {
    templates.push({
      key: `trigger:${trigger.event_type}`,
      kind: NodeKind.trigger,
      type: "trigger.event",
      label: trigger.label,
      group: `${TRIGGER_GROUP} · ${trigger.group}`,
      keywords: `${trigger.event_type} ${trigger.group} when on event`,
      params: { event: trigger.event_type },
    });
  }
  // Trigger KINDS (RADD-1323) — the button, the clock, the draft check and
  // any a plugin registers — from the catalog, like the events above.
  for (const kind of catalog?.trigger_kinds ?? []) {
    templates.push({
      key: `trigger:${kind.key}`,
      kind: NodeKind.trigger,
      type: "trigger.event",
      label: kind.label,
      group: `${TRIGGER_GROUP} · ${kind.group}`,
      keywords: `${kind.key} ${kind.group} ${kind.description}`,
      params: { event: kind.key, ...kind.default_params },
    });
  }

  // Every other node from its served spec, so the palette cannot offer what the server does not run.
  for (const node of catalog?.nodes ?? []) {
    if (node.kind === NodeKind.trigger) continue;
    const params =
      node.default_params && Object.keys(node.default_params).length
        ? { ...node.default_params }
        : defaultsFromSchema(node.params_schema);
    templates.push({
      key: node.key,
      kind: node.kind,
      type: node.key,
      label: node.label,
      group: node.group,
      keywords: `${node.key} ${node.keywords ?? ""} ${node.description}`,
      params,
      produces: isProducer({ type: node.key, params }, catalog),
    });
  }

  return templates;
}

/** Palette order: work-shaped trigger groups first; an unlisted group keeps registry order after these. */
const GROUP_ORDER = [
  `${TRIGGER_GROUP} · Items`,
  `${TRIGGER_GROUP} · Comments`,
  `${TRIGGER_GROUP} · Scheduled`,
  `${TRIGGER_GROUP} · On demand`,
  `${TRIGGER_GROUP} · Intake`,
  `${TRIGGER_GROUP} · Service desk`,
  `${TRIGGER_GROUP} · Pages`,
  `${TRIGGER_GROUP} · Time logging`,
  `${TRIGGER_GROUP} · Links`,
  `${TRIGGER_GROUP} · Attachments`,
  `${TRIGGER_GROUP} · Releases`,
  `${TRIGGER_GROUP} · Cycles`,
  `${TRIGGER_GROUP} · Email`,
  `${TRIGGER_GROUP} · People`,
  `${TRIGGER_GROUP} · Admin`,
  "Sources",
  "Filters",
  "Gates",
  "Actions",
];

/** Rows grouped by key, groups in first-seen order (`Map.groupBy` is ES2024; the lib is ES2022). */
export function groupBy<T>(rows: Iterable<T>, keyOf: (row: T) => string): [string, T[]][] {
  const groups = new Map<string, T[]>();
  for (const row of rows) {
    const key = keyOf(row);
    const group = groups.get(key);
    if (group) group.push(row);
    else groups.set(key, [row]);
  }
  return [...groups.entries()];
}

/** Templates by group, in the palette's order. */
export function groupTemplates(templates: NodeTemplate[]): [string, NodeTemplate[]][] {
  const rank = (group: string) => {
    const index = GROUP_ORDER.indexOf(group);
    // Unlisted trigger groups (a plugin's) sit after the listed triggers and
    // before the node kinds; unlisted node groups (a plugin's actions) go last.
    if (index >= 0) return index;
    return group.startsWith(TRIGGER_GROUP) ? GROUP_ORDER.indexOf("Sources") - 0.5 : GROUP_ORDER.length;
  };
  return groupBy(templates, (template) => template.group).sort(([a], [b]) => rank(a) - rank(b));
}

/** What a node is CALLED on the canvas (RADD-1265): the palette label of its
 * type, and for a trigger the event's label — never the wire key. Indexed once
 * per catalog because the canvas asks for every node on every rebuild. */
export function titleIndex(catalog: AutomationCatalog | undefined): Map<string, string> {
  const index = new Map<string, string>();
  for (const template of nodeTemplates(catalog)) index.set(template.key, template.label);
  return index;
}

export function nodeTitle(
  node: { kind: NodeKindValue; type: string; params: Record<string, unknown> },
  titles: Map<string, string>,
): string {
  if (node.kind === NodeKind.trigger) {
    const event = String(node.params.event ?? "");
    return titles.get(`trigger:${event}`) ?? event ?? node.type;
  }
  return titles.get(node.type) ?? node.type;
}

/** A fresh automation opens on a placed "Item updated" trigger. */
export function seededTrigger(): AutomationNode {
  return {
    id: "trg1",
    kind: NodeKind.trigger,
    type: "trigger.event",
    params: { event: "item.updated" },
    x: 0,
    y: 0,
  };
}

/** Case-insensitive match over label, group and keywords. */
export function searchTemplates(templates: NodeTemplate[], query: string): NodeTemplate[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return templates;
  const words = needle.split(/\s+/);
  return templates.filter((template) => {
    const haystack = `${template.label} ${template.group} ${template.keywords}`.toLowerCase();
    return words.every((word) => haystack.includes(word));
  });
}

/** Recipient values that name a ROLE rather than an address. Mirrors the
 * server's `EmailRecipient`; `notify_user` has no `contact` because a mail
 * contact has no account to notify in-app. */
const EMAIL_ROLES = new Set(["reporter", "assignee", "contact"]);
const NOTIFY_ROLES = new Set(["reporter", "assignee"]);

/** Why arity is not a choice right now, or "". A role recipient is a property of ONE issue: at set arity,
 * `send_email` to `reporter` resolves nobody and skip-logs. The server refuses the pairing. */
export function arityForcedReason(node: {
  type: string;
  params: Record<string, unknown>;
}): string {
  const target = String(
    node.type === "action.send_email" ? node.params.to ?? "" : node.params.user ?? "",
  ).toLowerCase();
  const roles =
    node.type === "action.send_email"
      ? EMAIL_ROLES
      : node.type === "action.notify_user"
        ? NOTIFY_ROLES
        : null;
  if (!roles || !roles.has(target)) return "";
  return `“${target}” is a property of one issue, so this runs once per item. Name an address to send a single digest instead.`;
}

/** Params with arity forced to per-item when a role recipient implies it — on edit, so the control
 * never disagrees with what saves. */
export function normalizeActionParams(
  node: { type: string },
  params: Record<string, unknown>,
): Record<string, unknown> {
  return arityForcedReason({ type: node.type, params })
    ? { ...params, arity: NodeArity.item }
    : params;
}

/** A fresh node id that does not collide with anything already in the graph. */
function nextNodeId(existing: AutomationNode[], kind: NodeKindValue): string {
  const prefix = { trigger: "trg", source: "find", filter: "flt", gate: "gate", action: "act" }[kind] ?? "n";
  for (let n = 1; ; n++) {
    const candidate = `${prefix}${n}`;
    if (!existing.some((node) => node.id === candidate)) return candidate;
  }
}

export function instantiate(
  template: NodeTemplate,
  existing: AutomationNode[],
  at: { x: number; y: number },
): AutomationNode {
  return {
    id: nextNodeId(existing, template.kind),
    kind: template.kind,
    type: template.type,
    // A producer arrives named (`generate_1`) so its output is reachable.
    name: template.produces ? suggestNodeName(template.type, existing) : undefined,
    // Cloned (no shared params) and normalised: send_email's default `reporter` implies per-item.
    params: normalizeActionParams(template, structuredClone(template.params)),
    x: at.x,
    y: at.y,
  };
}
