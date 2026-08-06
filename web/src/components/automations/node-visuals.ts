/**
 * Shared node iconography and colour (spec 116).
 *
 * Split out of GraphCanvas so the panel, the right-click menu and the canvas
 * itself agree — a filter that is blue in the list and green on the canvas is a
 * small thing that makes a graph harder to read than it needs to be.
 *
 * These reference tokens that EXIST AT RUNTIME. `--color-*` names live in
 * Tailwind's `@theme` block and compile into utilities, so `var(--color-…)`
 * resolves to nothing in an inline style — which is how the first version of the
 * edges shipped black on a dark canvas.
 */
import { Filter, GitBranch, Play, Search, Zap, type LucideIcon } from "lucide-react";
import { NodeKind, type NodeKindValue } from "../../lib/types";

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
};

export const INLET_TONE = "var(--color-emphasis)";
export const GRID_TONE = "var(--color-zinc-800)";

export const PORTS_BY_KIND: Record<string, string[]> = {
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

/**
 * A node's OUTPUT PORTS — from its type when the type decides, else its kind.
 *
 * The AI classifier's ports are the answers someone typed, so this cannot be a
 * per-kind table: the canvas has to redraw the node as the form changes, and the
 * server validates edges against exactly this set.
 */
export function portsOfNode(node: { kind: NodeKindValue; type: string; params: Record<string, unknown> }): string[] {
  if (node.type === "ai.classify") {
    const answers = ((node.params.answers as string[]) ?? [])
      .map((a) => String(a).trim())
      .filter(Boolean);
    return [...new Set(answers)].slice(0, 8).concat("unavailable");
  }
  return PORTS_BY_TYPE[node.type] ?? PORTS_BY_KIND[node.kind] ?? ["out"];
}
