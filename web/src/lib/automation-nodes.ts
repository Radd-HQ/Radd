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
  MANUAL_TRIGGER,
  NodeArity,
  NodeKind,
  SCHEDULE_TRIGGER,
  VALIDATE_TRIGGER,
  VALIDATION_FAIL_TYPE,
  type AutomationCatalog,
  type AutomationNode,
  type NodeArityInfo,
  type NodeArityValue,
  type NodeKindValue,
} from "./types/automations";
import { ACTION_TYPE_LABELS, ACTION_TYPE_ORDER } from "./meta";
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

/** Params a fresh node needs to be valid enough to save. The action union
 * validates these server-side, so an empty object would 422 on the first save
 * rather than when the field is finally filled in. */
function blankActionParams(actionType: string): Record<string, unknown> {
  switch (actionType) {
    case "set_state": return { state: "" };
    case "set_priority": return { priority: "normal" };
    case "set_assignee": return { assignee: "" };
    case "assign_round_robin": return { team: "" };
    case "set_team": return { team: "" };
    case "add_label":
    case "remove_label": return { label: "" };
    case "set_cycle": return { cycle: "" };
    case "set_release": return { release: "" };
    case "add_comment": return { body: "", visibility: "public" };
    case "set_custom_field": return { key: "", value: "" };
    case "create_item": return { project: "", title: "" };
    case "send_webhook": return { url: "https://" };
    case "post_chat": return { webhook_url: "https://", message: "" };
    case "notify_user": return { user: "", message: "" };
    case "send_email": return { to: "reporter", subject: "", body: "" };
    default: return {};
  }
}

const TRIGGER_GROUP = "Triggers";

interface SchemaProperty {
  type?: string;
  default?: unknown;
  enum?: unknown[];
  properties?: Record<string, SchemaProperty>;
  required?: string[];
}

/** Starting params for a contributed node, from its JSON Schema.
 * Only the shapes the schema can express — an object of typed properties —
 * because anything cleverer would be a second validator disagreeing with the
 * server's.
 *
 * Exported since RADD-1064: it is what a stored value is REPAIRED against when
 * the value's shape does not match the schema's, and the generated form needs
 * the same answer this does. */
export function defaultsFromSchema(schema: Record<string, unknown>): Record<string, unknown> {
  const properties = (schema.properties ?? {}) as Record<string, SchemaProperty>;
  const required = new Set((schema.required as string[]) ?? []);
  const out: Record<string, unknown> = {};
  for (const [key, property] of Object.entries(properties)) {
    if (property.default !== undefined) out[key] = property.default;
    // A REQUIRED enum takes its first member (RADD-923): "" would be a node
    // that fails validation the moment it is dropped, which reads as the
    // plugin being broken rather than as a field waiting to be filled.
    else if (property.enum?.length && required.has(key)) out[key] = property.enum[0];
    else if (property.type === "array") out[key] = [];
    // An OBJECT property recurses (RADD-1064). `ai.validate`'s `include` has no
    // default of its own — the defaults live one level down, on each boolean —
    // so a freshly dropped node used to carry no `include` at all, and the
    // sub-defaults existed only in the server's `ContextOptions.from_params`.
    // Two copies of "description is on, comments are off", agreeing by luck.
    else if (property.type === "object") out[key] = defaultsFromSchema(property as Record<string, unknown>);
    else if (property.type === "string") out[key] = "";
    else if (property.type === "number" || property.type === "integer") out[key] = 0;
    else if (property.type === "boolean") out[key] = false;
  }
  return out;
}

/** Static ports by node type, from the served catalog (RADD-1064).
 *
 * Only the types that DECLARE a fixed set appear: an empty `ports` means the
 * node's outputs depend on its params, and the canvas computes those itself. */
export function contributedPorts(
  catalog: AutomationCatalog | undefined,
): Record<string, string[]> {
  const map: Record<string, string[]> = {};
  for (const node of catalog?.contributed_nodes ?? []) {
    if (node.ports?.length) map[node.key] = node.ports;
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
  templates.push({
    key: `trigger:${SCHEDULE_TRIGGER}`,
    kind: NodeKind.trigger,
    type: "trigger.event",
    label: "On a schedule",
    group: `${TRIGGER_GROUP} · Scheduled`,
    keywords: "schedule cron daily weekly interval recurring every",
    // A schedule trigger PRODUCES its item set from `query` — it has no event and
    // so no target item. An empty query is legal and means "no items": the
    // universal actions still run, which is how "post to chat every Monday" works.
    params: { event: SCHEDULE_TRIGGER, schedule: { kind: "interval", minutes: 30 }, query: "" },
  });
  templates.push({
    key: `trigger:${VALIDATE_TRIGGER}`,
    kind: NodeKind.trigger,
    type: "trigger.event",
    label: "When someone submits (validate it)",
    group: `${TRIGGER_GROUP} · Intake`,
    keywords: "validate validation intake check quality submit form required advisory gate",
    // No targets and advisory by default: a trigger that governed something the
    // moment it was dropped could refuse a real submission before its author
    // had finished writing the graph.
    params: { event: VALIDATE_TRIGGER, targets: [], mode: "advisory" },
  });
  templates.push({
    key: `trigger:${MANUAL_TRIGGER}`,
    kind: NodeKind.trigger,
    type: "trigger.event",
    label: "Manual (run from the / menu)",
    group: `${TRIGGER_GROUP} · On demand`,
    keywords: "manual on demand run button slash quick action",
    params: { event: MANUAL_TRIGGER },
  });

  templates.push({
    key: "search.slq",
    kind: NodeKind.source,
    type: "search.slq",
    label: "Find issues (SLQ)",
    group: "Sources",
    keywords: "search find query slq lookup fetch produce items source others related",
    // REPLACE by default: the common case reaches somewhere else entirely, and a
    // silent union would make the result depend on whatever the trigger carried.
    params: { slq: "", project: "", mode: "replace" },
  });

  templates.push({
    key: "filter.slq",
    kind: NodeKind.filter,
    type: "filter.slq",
    label: "Filter items (SLQ)",
    group: "Filters",
    keywords: "slq query where narrow matched unmatched branch condition if",
    params: { slq: "" },
  });

  // Named single tests, not one abstract condition tree. The GRAPH already
  // composes booleans — chaining gates is AND, fanning out and merging is OR,
  // the `false` port is NOT — so each node can be one plain question. The old
  // `gate.event` still executes for stored graphs but is no longer offered:
  // a node called "event conditions" taught nobody what it tested.
  templates.push({
    key: "gate.field_changed",
    kind: NodeKind.gate,
    type: "gate.field_changed",
    label: "Field changed",
    group: "Gates",
    keywords: "field changed from to transition state priority assignee custom moved became",
    params: {
      field: "state",
      from_mode: "any",
      from_values: [],
      to_mode: "any",
      to_values: [],
    },
  });
  templates.push({
    key: "gate.changed_by",
    kind: NodeKind.gate,
    type: "gate.changed_by",
    label: "Changed by",
    group: "Gates",
    keywords: "who actor person user did it made the change author",
    params: { users: [], negate: false },
  });
  templates.push({
    key: "gate.state_category",
    kind: NodeKind.gate,
    type: "gate.state_category",
    label: "State category is",
    group: "Gates",
    keywords: "category done canceled progress todo backlog triage finished closed",
    params: { categories: [] },
  });

  // Contributed nodes (spec 116 phase 2) — the AI classifier and anything a
  // plugin adds. Their default params come from the schema's own defaults so a
  // freshly dropped node is valid enough to save.
  for (const node of catalog?.contributed_nodes ?? []) {
    const params = defaultsFromSchema(node.params_schema);
    templates.push({
      key: node.key,
      kind: node.kind,
      type: node.key,
      label: node.label,
      group: node.group,
      keywords: `${node.key} ${node.description}`,
      params,
      produces: isProducer({ type: node.key, params }, catalog),
    });
  }

  // The spec-119 check. An ACTION kind on the server (its ports are an action's
  // single `out`), so it belongs here rather than among the gates — it does not
  // route, it says something and passes the packet on.
  templates.push({
    key: VALIDATION_FAIL_TYPE,
    kind: NodeKind.action,
    type: VALIDATION_FAIL_TYPE,
    label: "Report a problem",
    group: "Actions",
    keywords: "validation fail finding reject refuse check problem intake quality require",
    params: { message: "", field: "" },
  });

  for (const actionType of ACTION_TYPE_ORDER) {
    const params = blankActionParams(actionType);
    templates.push({
      key: `action.${actionType}`,
      kind: NodeKind.action,
      type: `action.${actionType}`,
      label: ACTION_TYPE_LABELS[actionType],
      group: "Actions",
      keywords: `${actionType} do apply`,
      params,
      produces: isProducer({ type: `action.${actionType}`, params }, catalog),
    });
  }

  return templates;
}

/** Templates by group, in the order the groups first appear. */
export function groupTemplates(templates: NodeTemplate[]): [string, NodeTemplate[]][] {
  const grouped = new Map<string, NodeTemplate[]>();
  for (const template of templates) {
    grouped.set(template.group, [...(grouped.get(template.group) ?? []), template]);
  }
  return [...grouped.entries()];
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

/** How a node type may read its packet, from the served table.
 *
 * Defaults to "fixed at set" for an unknown type rather than guessing: an
 * automation holding a node from a plugin that has been uninstalled must still
 * open, and offering a control that the server would reject is worse than
 * offering none. */
export function arityOf(
  catalog: AutomationCatalog | undefined,
  nodeType: string,
): NodeArityInfo {
  return (
    catalog?.node_arity?.find((entry) => entry.type === nodeType) ?? {
      type: nodeType,
      default: NodeArity.set,
      options: [NodeArity.set],
    }
  );
}

/** The arity a node will actually run at: its stored choice when the type
 * offers one, else the type's default. Mirrors `nodes.arity_of` on the server —
 * the badge on the card has to say what the engine will do. */
export function effectiveArity(
  catalog: AutomationCatalog | undefined,
  node: { type: string; params: Record<string, unknown> },
): NodeArityValue {
  const rule = arityOf(catalog, node.type);
  if (rule.options.length < 2) return rule.default;
  const chosen = String(node.params.arity ?? "");
  return (rule.options as string[]).includes(chosen)
    ? (chosen as NodeArityValue)
    : rule.default;
}

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
