/** Named outputs and upstream reachability, over explicit server-resolved shapes. */
import { shapeOf, type NodeShapes } from "./shape-contract";
import {
  NodeArity,
  type AutomationCatalog,
  type AutomationEdge,
  type AutomationNode,
  type NodeArityInfo,
  type NodeArityValue,
  type OutputFieldInfo,
} from "./types";

/** Mirrors the kernel's `OUTPUT_NAME_RE`. Both halves of `{{node.field}}` are
 * read as one identifier, so one rule covers a node's name and an output's. */
const OUTPUT_NAME_RE = /^[a-z][a-z0-9_]{0,29}$/;

/** Named values from this graph's resolved shape, or the type's fixed catalog. */
export function outputsOfNode(
  node: Pick<AutomationNode, "type" | "params">,
  catalog: AutomationCatalog | undefined,
  shapes?: NodeShapes,
): OutputFieldInfo[] {
  // Dynamic outputs are supplied by the caller for these exact params.
  const shape = shapeOf(node, shapes);
  if (shape) return shape.outputs;
  return catalog?.nodes?.find((entry) => entry.key === node.type)?.outputs ?? [];
}

/** How a node type may read its packet. Unknown (plugin uninstalled) = fixed at set, so the automation still opens. */
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

/** Whether a node type can be given a name at all — i.e. whether naming it would
 * make anything addressable. Asked of the TYPE plus its current params, because
 * `ai.generate` with no fields still produces `text`. */
export function isProducer(
  node: Pick<AutomationNode, "type" | "params">,
  catalog: AutomationCatalog | undefined,
  shapes?: NodeShapes,
): boolean {
  return outputsOfNode(node, catalog, shapes).length > 0;
}

/**
 * Whether a node's outputs travel out by `port`. Mirrors the executor: a ROUTER's LAST port is its
 * fallback, taken when it could not answer — so it published nothing. Actions' ports all carry
 * (`create_item` stamps both `out` and `created`).
 */
function portCarriesOutputs(
  node: Pick<AutomationNode, "type" | "params">,
  port: string,
  catalog: AutomationCatalog | undefined,
  shapes?: NodeShapes,
): boolean {
  const contributed = catalog?.nodes?.find((entry) => entry.key === node.type);
  if (!contributed || (contributed.kind !== "gate" && contributed.kind !== "filter")) return true;
  const ports = contributed.ports?.length ? contributed.ports : (shapeOf(node, shapes)?.ports ?? []);
  return ports.length === 0 ? true : port !== ports[ports.length - 1];
}

/** Per-item invocations publish nothing (the packet holds one slot per node), so their tokens always miss. */
function publishesOutputs(
  node: Pick<AutomationNode, "type" | "params">,
  catalog: AutomationCatalog | undefined,
): boolean {
  return effectiveArity(catalog, node) !== NodeArity.item;
}

/** Producers whose values can REACH this node, nearest first — a backwards BFS carrying each producer's
 * out-port. Skipped (tokens that would save and resolve to nothing): not upstream, upstream only via its
 * fallback port, per-item arity, unnamed. Only the producer's own port matters: once in the packet,
 * values ride every downstream port. */
export function upstreamProducers(
  nodeId: string,
  nodes: AutomationNode[],
  edges: AutomationEdge[],
  catalog: AutomationCatalog | undefined,
  shapes?: NodeShapes,
): { node: AutomationNode; outputs: OutputFieldInfo[] }[] {
  const incoming = new Map<string, { source: string; port: string }[]>();
  for (const edge of edges) {
    incoming.set(edge.target, [
      ...(incoming.get(edge.target) ?? []),
      { source: edge.source, port: edge.port },
    ]);
  }
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const seen = new Set([nodeId]);
  const queue = [nodeId];
  //: producer id -> the ports through which it reaches the edited node.
  const reachesBy = new Map<string, Set<string>>();
  const order: string[] = [];
  while (queue.length) {
    const id = queue.shift() as string;
    for (const { source, port } of incoming.get(id) ?? []) {
      reachesBy.set(source, (reachesBy.get(source) ?? new Set()).add(port));
      if (seen.has(source)) continue;
      seen.add(source);
      order.push(source);
      queue.push(source);
    }
  }

  const found: { node: AutomationNode; outputs: OutputFieldInfo[] }[] = [];
  for (const id of order) {
    const node = byId.get(id);
    if (!node) continue;
    const outputs = outputsOfNode(node, catalog, shapes);
    // A producer with no NAME is skipped: it produces, but nothing can address
    // it, and offering `{{.field}}` would be offering a token that cannot work.
    if (!node.name || outputs.length === 0) continue;
    if (!publishesOutputs(node, catalog)) continue;
    const ports = [...(reachesBy.get(id) ?? [])];
    if (!ports.some((port) => portCarriesOutputs(node, port, catalog, shapes))) continue;
    found.push({ node, outputs });
  }
  return found;
}

/** `ai.generate` → `generate_1`. Naming is the client's job; the server has no opinion. */
export function suggestNodeName(type: string, existing: AutomationNode[]): string {
  const base =
    (type.split(".").pop() ?? type).replace(/[^a-z0-9_]/gi, "_").toLowerCase() || "node";
  const stem = OUTPUT_NAME_RE.test(base) ? base : `n_${base}`.slice(0, 30);
  const taken = new Set(existing.map((node) => node.name).filter(Boolean));
  for (let n = 1; ; n++) {
    const candidate = `${stem}_${n}`.slice(0, 30);
    if (!taken.has(candidate)) return candidate;
  }
}

/** Why this name cannot be used, or "": the server's three refusals, said before save. Reserved = the
 * served token roots, since a node called `item` would silently shadow `{{item.key}}`. */
export function nodeNameError(
  name: string,
  self: AutomationNode,
  nodes: AutomationNode[],
  catalog: AutomationCatalog | undefined,
): string {
  const trimmed = name.trim();
  if (!trimmed) return "";
  if (!OUTPUT_NAME_RE.test(trimmed)) {
    return "Lowercase letters, digits and underscores, starting with a letter.";
  }
  if (reservedRoots(catalog).has(trimmed)) {
    return `“${trimmed}” is already a template word — it would shadow {{${trimmed}.…}}.`;
  }
  const clash = nodes.find((node) => node.id !== self.id && node.name === trimmed);
  return clash ? `Node ${clash.id} is already called “${trimmed}”.` : "";
}

/** The first segment of every documented token. Derived from the served
 * catalogue, exactly as the server derives its own reserved set. */
function reservedRoots(catalog: AutomationCatalog | undefined): Set<string> {
  return new Set(
    (catalog?.tokens ?? []).map((entry) => entry.token.replace(/[{}\s]/g, "").split(".")[0]),
  );
}
