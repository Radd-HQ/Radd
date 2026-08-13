/**
 * What a node PRODUCES, and which producers a node can read from (spec 120).
 *
 * The mirror of `node-visuals.portsOfNode`, and it exists for the same reason:
 * the editor has to answer "what can this node emit" BEFORE anything has run,
 * and for a node whose answer depends on its params it has to keep answering as
 * the form is edited. So the ranking is the server's — a type's DECLARED outputs
 * first, then the params-dependent ones, then the built-in table — and the
 * dynamic cases are computed here because the server cannot be asked about a
 * params dict that is still being typed.
 *
 * The topology half matters just as much. A token picker that offered every
 * named node in the graph would offer values from branches this one cannot be
 * reached from, and those resolve to nothing at run time. Walking the edges
 * BACKWARDS is what makes the picker's list the same list the run will have.
 */
import {
  NodeArity,
  type AutomationCatalog,
  type AutomationEdge,
  type AutomationNode,
  type NodeArityInfo,
  type NodeArityValue,
  type OutputFieldInfo,
} from "./types/automations";

/** Mirrors the kernel's `OUTPUT_NAME_RE`. Both halves of `{{node.field}}` are
 * read as one identifier, so one rule covers a node's name and an output's. */
export const OUTPUT_NAME_RE = /^[a-z][a-z0-9_]{0,29}$/;

const field = (
  name: string,
  description = "",
  kind = "text",
  choices: string[] = [],
): OutputFieldInfo => ({ name, label: name, kind, choices, description });

/**
 * The named values a node produces.
 *
 * `ai.generate`'s outputs ARE its params — the fields someone is still typing —
 * and `ai.classify`'s enum choices are the answers being typed, so both are
 * computed locally. Everything else comes from the served catalog, which covers
 * built-in producers (`node_outputs`) and contributed ones with fixed outputs
 * (`contributed_nodes[].outputs`) in one ranking.
 */
export function outputsOfNode(
  node: Pick<AutomationNode, "type" | "params">,
  catalog: AutomationCatalog | undefined,
): OutputFieldInfo[] {
  if (node.type === "ai.generate") {
    return [
      field("text", "The model's own words about this item."),
      ...generateFields(node.params).map((entry) =>
        field(entry.name, entry.description ?? "", entry.kind, entry.choices ?? []),
      ),
    ];
  }
  if (node.type === "ai.classify") {
    const answers = [
      ...new Set(
        ((node.params.answers as string[]) ?? []).map((a) => String(a).trim()).filter(Boolean),
      ),
    ].slice(0, 8);
    return answers.length >= 2
      ? [field("answer", "The answer the model chose.", "enum", answers)]
      : [];
  }
  const contributed = catalog?.contributed_nodes?.find((entry) => entry.key === node.type);
  if (contributed?.outputs?.length) return contributed.outputs;
  return catalog?.node_outputs?.find((entry) => entry.type === node.type)?.outputs ?? [];
}

/** One declared field of an `ai.generate` node, as the form stores it. */
export interface GenerateField {
  name: string;
  kind: string;
  choices?: string[];
  description?: string;
}

/** The stored `fields` list, read defensively — a hand-edited row (or a node
 * saved by an older build) must render as something rather than crash the
 * inspector. */
export function generateFields(params: Record<string, unknown>): GenerateField[] {
  const raw = params.fields;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === "object")
    .map((entry) => ({
      name: String(entry.name ?? ""),
      kind: String(entry.kind ?? "text"),
      choices: Array.isArray(entry.choices) ? entry.choices.map(String) : [],
      description: String(entry.description ?? ""),
    }));
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

/** Whether a node type can be given a name at all — i.e. whether naming it would
 * make anything addressable. Asked of the TYPE plus its current params, because
 * `ai.generate` with no fields still produces `text`. */
export function isProducer(
  node: Pick<AutomationNode, "type" | "params">,
  catalog: AutomationCatalog | undefined,
): boolean {
  return outputsOfNode(node, catalog).length > 0;
}

/**
 * Whether values a node produced can travel out by this PORT.
 *
 * Mirrors the executor. A contributed router's LAST port is its fallback — the
 * one taken when the node could not answer — and a node that could not answer
 * published nothing, so no output ever travels it. `ai.generate`'s
 * `unavailable` and `ai.classify`'s are exactly that port, and a token picker
 * that ignored the distinction would offer `{{gen.text}}` to a node wired to
 * the branch where `gen` produced nothing by construction.
 *
 * Built-in producers have no fallback: `create_item` stamps both `out` and
 * `created`, so both carry.
 */
export function portCarriesOutputs(
  node: Pick<AutomationNode, "type" | "params">,
  port: string,
  catalog: AutomationCatalog | undefined,
): boolean {
  const contributed = catalog?.contributed_nodes?.find((entry) => entry.key === node.type);
  if (!contributed) return true;
  const ports = contributed.ports?.length
    ? contributed.ports
    : // Dynamic ports: the client computes them the same way the canvas does.
      (node.type === "ai.classify"
        ? [
            ...new Set(
              ((node.params.answers as string[]) ?? []).map((a) => String(a).trim()).filter(Boolean),
            ),
          ].slice(0, 8).concat("unavailable")
        : []);
  return ports.length === 0 ? true : port !== ports[ports.length - 1];
}

/**
 * Whether this node PUBLISHES what it produces at all.
 *
 * A per-item invocation makes one answer per item and the packet's bag has one
 * slot per node, so the executor drops them — a node set to "per item" produces
 * values that nothing can ever read, and offering its tokens would be offering
 * misses.
 */
export function publishesOutputs(
  node: Pick<AutomationNode, "type" | "params">,
  catalog: AutomationCatalog | undefined,
): boolean {
  return effectiveArity(catalog, node) !== NodeArity.item;
}

/** Producers whose values can actually REACH this node, nearest first.
 *
 * A breadth-first walk backwards along the edges, carrying the PORT each
 * producer would leave by. Three things disqualify a producer, and each is a
 * token that would compile, save, and resolve to nothing:
 *
 *   - it is not upstream at all (a different branch entirely);
 *   - it is upstream only through a port that carries no outputs — its
 *     fallback, taken exactly when it produced nothing;
 *   - it runs per ITEM, so the executor publishes nothing for it.
 *
 * Only the FIRST edge out of the producer matters. Once its values are in the
 * packet they ride every port of every node they pass through, so a gate two
 * hops down taking its `false` port carries them just the same. */
export function upstreamProducers(
  nodeId: string,
  nodes: AutomationNode[],
  edges: AutomationEdge[],
  catalog: AutomationCatalog | undefined,
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
    const outputs = outputsOfNode(node, catalog);
    // A producer with no NAME is skipped: it produces, but nothing can address
    // it, and offering `{{.field}}` would be offering a token that cannot work.
    if (!node.name || outputs.length === 0) continue;
    if (!publishesOutputs(node, catalog)) continue;
    const ports = [...(reachesBy.get(id) ?? [])];
    if (!ports.some((port) => portCarriesOutputs(node, port, catalog))) continue;
    found.push({ node, outputs });
  }
  return found;
}

/** A name suggestion for a freshly dropped producer: the type's last segment
 * plus a counter, so `ai.generate` arrives as `generate_1`.
 *
 * Auto-naming is the CLIENT's job by design — the server has no opinion about
 * what a node should be called, and a producer that arrives unnamed is a node
 * whose whole point is unreachable until someone notices the field. */
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

/** Why this name cannot be used, or "" when it can.
 *
 * The same three refusals the server makes, said before the save rather than
 * after it. The RESERVED list is the roots of the served token catalogue, so it
 * cannot drift from what the server reserves: a node called `item` would shadow
 * `{{item.key}}` everywhere in the graph, and the shadowing would be invisible
 * because the token would keep resolving. */
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
export function reservedRoots(catalog: AutomationCatalog | undefined): Set<string> {
  return new Set(
    (catalog?.tokens ?? []).map((entry) => entry.token.replace(/[{}\s]/g, "").split(".")[0]),
  );
}
