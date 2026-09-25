import { defaultsFromSchema } from "@radd/plugin-sdk";
/**
 * The node catalogue: everything that can be dropped on the canvas (spec 116).
 *
 * One list, consumed by BOTH the left panel and the right-click menu, so the two
 * can never offer different things. A palette that disagrees with the search is
 * the kind of drift that makes people distrust the search.
 *
 * Triggers come from the SERVER's event catalogue rather than a hardcoded list —
 * `GET /automations/catalog` already knows every subscribable event and which
 * group it belongs to, and hardcoding a copy here would go stale the first time
 * a module adds an event type.
 */
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

/** Static ports by node type, from the served catalog (RADD-1064).
 *
 * Only the types that DECLARE a fixed set appear: an empty `ports` means the
 * node's outputs depend on its params, and the canvas computes those itself. */
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

  // Every other node — built-in and contributed alike (RADD-1322) — from the
  // served catalog: its label, group, search words and starting params are the
  // spec's own, so the palette cannot offer a node the server does not run.
  // Triggers come from the trigger catalogue above, not from here.
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

/** The palette's order (RADD-1265). The registry lists event groups in load
 * order, which put twenty admin triggers above Items; people reach for the
 * work-shaped groups first, the on-demand starters, then the rest. A group not
 * named here keeps its registry position after the named ones. */
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

/** Templates by group, in the palette's order. */
export function groupTemplates(templates: NodeTemplate[]): [string, NodeTemplate[]][] {
  const grouped = new Map<string, NodeTemplate[]>();
  for (const template of templates) {
    grouped.set(template.group, [...(grouped.get(template.group) ?? []), template]);
  }
  const rank = (group: string) => {
    const index = GROUP_ORDER.indexOf(group);
    // Unlisted trigger groups (a plugin's) sit after the listed triggers and
    // before the node kinds; unlisted node groups (a plugin's actions) go last.
    if (index >= 0) return index;
    return group.startsWith(TRIGGER_GROUP) ? GROUP_ORDER.indexOf("Sources") - 0.5 : GROUP_ORDER.length;
  };
  return [...grouped.entries()].sort(([a], [b]) => rank(a) - rank(b));
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

/** A fresh automation's first node (RADD-1265): an "Item updated" trigger,
 * placed and selected, so the editor opens on a question ("fires on…") rather
 * than an empty canvas. */
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

// `arityOf` / `effectiveArity` live in `automation-outputs.ts` since RADD-1073's
// review: the PUBLISH rules there need to know a producer's arity (an item-arity
// node publishes nothing), and this module already depends on that one. Moving
// them down keeps the dependency one-way; re-exported so no call site moved.
export { arityOf, effectiveArity } from "./automation-outputs";

/** Recipient values that name a ROLE rather than an address. Mirrors the
 * server's `EmailRecipient`; `notify_user` has no `contact` because a mail
 * contact has no account to notify in-app. */
const EMAIL_ROLES = new Set(["reporter", "assignee", "contact"]);
const NOTIFY_ROLES = new Set(["reporter", "assignee"]);

/** Why a node's arity is not a choice right now, or "" when it is.
 *
 * A role recipient is a property of ONE issue. Addressed to `reporter` and run
 * once over a set, `send_email` resolves nobody and skip-logs — which is what
 * "email each reporter" did on every scheduled run until RADD-918: a saved,
 * enabled automation that had never once sent a message. The server refuses to
 * store that pairing; this is why, said before the save. */
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

/** Params with the arity corrected for what they now say.
 *
 * Applied on every param edit rather than at render: choosing a role recipient
 * IMPLIES per-item, and a control that silently disagrees with what will be
 * saved is worse than one that moves. */
export function normalizeActionParams(
  node: { type: string },
  params: Record<string, unknown>,
): Record<string, unknown> {
  return arityForcedReason({ type: node.type, params })
    ? { ...params, arity: NodeArity.item }
    : params;
}

/** A fresh node id that does not collide with anything already in the graph. */
export function nextNodeId(existing: AutomationNode[], kind: NodeKindValue): string {
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
    // A PRODUCER arrives named (spec 120). Its whole point is that something
    // downstream can read it, and an unnamed one is a node whose output is
    // unreachable until someone notices the field — so the editor suggests
    // `generate_1` and the person renames it if they care.
    name: template.produces ? suggestNodeName(template.type, existing) : undefined,
    // Cloned, not shared: two nodes from one template must not end up editing
    // the same params object. Normalised too — `send_email`'s blank params name
    // the `reporter` ROLE, which implies per-item, so a freshly dropped node
    // would otherwise arrive in the one state the server refuses to store.
    params: normalizeActionParams(template, structuredClone(template.params)),
    x: at.x,
    y: at.y,
  };
}
