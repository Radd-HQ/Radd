/**
 * Node iconography and colour, shared by panel, menu and canvas. Inline styles must use tokens that
 * exist at RUNTIME: Tailwind's `--color-*` compile into utilities, so `var(--color-…)` in a style
 * resolves to nothing (edges once shipped black on a dark canvas).
 */
import { Filter, Flag, GitBranch, OctagonX, Play, Search, Zap, type LucideIcon } from "lucide-react";
import { NodeKind, type NodeKindValue } from "./types";
import { shapeOf, type NodeShapes } from "./shape-contract";

export const NODE_KIND_ICON: Record<NodeKindValue, LucideIcon> = {
  [NodeKind.trigger]: Play,
  [NodeKind.source]: Search,
  [NodeKind.filter]: Filter,
  [NodeKind.gate]: GitBranch,
  [NodeKind.action]: Zap,
};

/** One hue per kind, so the shape of a graph reads before any label does. */
export const NODE_KIND_TONE: Record<NodeKindValue, string> = {
  [NodeKind.trigger]: "var(--chart-todo-ink)", // blue — where flow enters
  [NodeKind.source]: "var(--chart-todo-ink)", // blue too: it also brings items IN
  [NodeKind.filter]: "var(--chart-triage-ink)", // amber — a decision point
  [NodeKind.gate]: "var(--chart-triage-ink)",
  [NodeKind.action]: "var(--accent-text)", // accent — the thing that acts
};

/** Port colour by semantic. Green = the item took this path, grey = the other
 * way (not an error). The `-ink` tier because a thin line is read like text. */
export const PORT_TONE: Record<string, string> = {
  matched: "var(--chart-progress-ink)",
  true: "var(--chart-progress-ink)",
  unmatched: "var(--chart-backlog-ink)",
  false: "var(--chart-backlog-ink)",
  out: "var(--accent-text)",
  // What was made, not what came in — its own colour so the two outputs of a
  // create-item node are not mistaken for each other.
  created: "var(--chart-progress-ink)",
  // A check's verdict (`ai.validate`). Same green/grey pairing as matched /
  // unmatched: `fail` is a route, not an error — the packet went the other way.
  pass: "var(--chart-progress-ink)",
  fail: "var(--chart-backlog-ink)",
  // Only minor problems (RADD-1329): amber, like a warning.
  warn: "var(--chart-triage-ink)",
  // The provider could not answer. Amber because it is neither branch: nobody
  // decided anything, and a graph that wires it is saying what to do about that.
  unavailable: "var(--chart-triage-ink)",
};

/**
 * The two validation VERDICT nodes (RADD-1329) — the only things that can say
 * something to the person submitting. Their own shape and colour, so what
 * BLOCKS reads off the canvas without opening a node: red for "Block
 * submission", amber for "Warn submitter". Terminal — no outlet.
 */
export const VERDICT_VISUAL: Record<string, { icon: LucideIcon; tone: string; tag: string }> = {
  "verdict.block": { icon: OctagonX, tone: "var(--status-danger-ink)", tag: "Blocks" },
  "verdict.warn": { icon: Flag, tone: "var(--status-warning-ink)", tag: "Warns" },
};

/** Words a port is SHOWN as, where its wire key would read badly. */
export const PORT_LABEL: Record<string, string> = {
  unavailable: "can't check",
};

export const INLET_TONE = "var(--radd-text-muted)";
export const GRID_TONE = "var(--radd-border)";

const PORTS_BY_KIND: Record<string, string[]> = {
  [NodeKind.trigger]: ["out"],
  [NodeKind.source]: ["out"],
  [NodeKind.filter]: ["matched", "unmatched"],
  [NodeKind.gate]: ["true", "false"],
  [NodeKind.action]: ["out"],
};

/** Ports a built-in TYPE emits when they are not just its kind's. Mirrors the
 * server's `BUILTIN_PORTS`; the canvas has to draw the handle before the server
 * ever sees the graph. */
const PORTS_BY_TYPE: Record<string, string[]> = {
  "action.create_item": ["out", "created"],
};

/** A node's output ports, ranked as the server ranks them (`AutomationNodeSpec.ports_at`): declared
 * (a terminal node declares none), then server-resolved shape, then the built-in table, then the kind.
 * A handle drawn from any other precedence 409s on save. */
export function portsOfNode(
  node: { kind: NodeKindValue; type: string; params: Record<string, unknown> },
  contributedPorts?: Record<string, string[]>,
  shapes?: NodeShapes,
): string[] {
  const declared = contributedPorts?.[node.type];
  if (declared) return declared;
  const shape = shapeOf(node, shapes);
  if (shape) return shape.ports;
  return PORTS_BY_TYPE[node.type] ?? PORTS_BY_KIND[node.kind] ?? ["out"];
}
