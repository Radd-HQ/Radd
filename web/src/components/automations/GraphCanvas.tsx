/**
 * The automation node canvas (spec 116, RADD-916).
 *
 * React Flow supplies the canvas primitives only — pan, zoom, edge routing, port
 * hit-testing. Every pixel of a node is ours, drawn with house tokens and the
 * kit, which is the condition under which taking the dependency was worth it:
 * unlike Crepe it imposes no chrome we then have to fight.
 *
 * Ports are the whole point of the drawing. A FILTER emits `matched` and
 * `unmatched`, a GATE emits `true` and `false`, and those must be distinguishable
 * at a glance rather than by reading a label — so they are colour-coded and
 * always visible, not hover-revealed. (Hover-revealed chrome is also invisible to
 * a CDP proof at baseline, which is its own reason to avoid it here.)
 *
 * Nodes with no stored coordinates are laid out from the topology by
 * `automation-layout.ts`, so every automation migrated by d116graphs opens tidy
 * without a data migration guessing positions for graphs nobody had opened.
 */
import { useCallback, useEffect, useMemo } from "react";
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  useNodesState,
  useReactFlow,
  type Edge as FlowEdge,
  type Node as FlowNode,
  type NodeChange,
  type NodeProps,
  type Connection,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  NodeKind,
  type AutomationCatalog,
  type AutomationEdge,
  type AutomationNode,
  type NodeResult,
  type RuleTestResult,
} from "../../lib/types";
import { arityOf, effectiveArity } from "../../lib/automation-nodes";
import {
  GRID_TONE,
  INLET_TONE,
  NODE_KIND_ICON,
  NODE_KIND_TONE,
  PORT_TONE,
  portsOfNode,
} from "./node-visuals";
import { layout, NODE_WIDTH } from "../../lib/automation-layout";

interface NodeData extends Record<string, unknown> {
  node: AutomationNode;
  subtitle: string;
  orientation: Orientation;
  /** "item" when this node fans out — shown as a badge so the expensive part of
   * a graph is visible without opening every node. Empty when the type offers no
   * choice: a badge on `set_state` would say only what everyone assumes. */
  arity: string;
  /** This node's last dry run, when there has been one. */
  run?: NodeResult;
}

/** One node. Deliberately plain: kind icon, its type, and a one-line summary of
 * what it is configured to do — the canvas answers "what is the shape of this
 * automation", and the detail panel answers "what exactly does this node do". */
function GraphNode({ data, selected }: NodeProps) {
  const { node, subtitle, orientation, arity, run } = data as NodeData;
  // Flow enters the top and leaves the bottom when vertical; left/right when
  // horizontal. Getting this wrong draws every edge as a sideways loop.
  const inletSide = orientation === "vertical" ? Position.Top : Position.Left;
  const outletSide = orientation === "vertical" ? Position.Bottom : Position.Right;
  const Icon = NODE_KIND_ICON[node.kind];
  const ports = portsOfNode(node);

  return (
    <div
      style={{ width: NODE_WIDTH }}
      className={`rounded-[10px] border bg-surface px-3 py-2.5 shadow-lift ${
        selected ? "border-emphasis outline outline-2 outline-offset-1 outline-focus" : "border-strong"
      }`}
      data-node-kind={node.kind}
      data-node-id={node.id}
    >
      {node.kind !== NodeKind.trigger && (
        <Handle type="target" position={inletSide} style={{ background: INLET_TONE }} />
      )}
      <div className="flex items-center gap-1.5">
        <Icon size={13} className="shrink-0" style={{ color: NODE_KIND_TONE[node.kind] }} aria-hidden />
        <span className="truncate text-[11px] uppercase tracking-wide text-fg-muted">{node.kind}</span>
        {arity && (
          <span
            data-node-arity={arity}
            title={
              arity === "item"
                ? "Runs once for every item that reaches it"
                : "Runs once, however many items reach it"
            }
            className="ml-auto shrink-0 rounded-[4px] border border-subtle px-1 py-px text-[9px] uppercase tracking-wide text-fg-muted"
          >
            {arity === "item" ? "per item" : "once"}
          </span>
        )}
      </div>
      <div className="mt-0.5 truncate text-[13px] font-medium text-heading">{node.type}</div>
      {subtitle && <div className="mt-0.5 truncate text-[11px] text-fg-secondary">{subtitle}</div>}
      {run && (
        <div
          data-node-run={run.ran ? "ran" : "skipped"}
          className="mt-1 truncate text-[10px] text-fg-muted"
          title={run.incoming_sample.join(", ")}
        >
          {run.ran ? `${run.incoming} in` : "did not run"}
          {run.incoming_sample.length > 0 && ` · ${run.incoming_sample.slice(0, 3).join(", ")}`}
        </div>
      )}

      {ports.map((port, index) => (
        <Handle
          key={port}
          id={port}
          type="source"
          position={outletSide}
          style={{
            ...(orientation === "vertical"
              ? { left: `${((index + 1) / (ports.length + 1)) * 100}%` }
              : { top: `${((index + 1) / (ports.length + 1)) * 100}%` }),
            background: PORT_TONE[port] ?? INLET_TONE,
            width: 9,
            height: 9,
          }}
        />
      ))}
      {ports.length > 1 && (
        <div
          className={
            orientation === "vertical"
              ? "pointer-events-none absolute -bottom-1 left-0 flex w-full translate-y-full justify-evenly pt-1"
              : "pointer-events-none absolute -right-1 top-0 flex h-full flex-col justify-evenly"
          }
        >
          {ports.map((port) => {
            // After a dry run, each port says what actually left it. A branch
            // the node never emitted is struck through rather than shown as
            // "0" — "did not run" and "ran and found nothing" are different
            // answers and the second one is where people go looking for a bug.
            const outcome = run?.ports.find((entry) => entry.port === port);
            return (
              <span
                key={port}
                data-port-label={port}
                className={
                  (orientation === "vertical"
                    ? "text-[9px] uppercase tracking-wide"
                    : "translate-x-full pl-2.5 text-[9px] uppercase tracking-wide") +
                  (outcome && !outcome.taken ? " line-through opacity-60" : "")
                }
                style={{ color: PORT_TONE[port] }}
              >
                {port}
                {outcome && (outcome.taken ? ` ${outcome.count}` : "")}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

const nodeTypes = { radd: GraphNode };

/**
 * Refit the view when the node COUNT changes.
 *
 * `fitView` as a prop only runs on mount, so a node added afterwards keeps the
 * old viewport — and since new nodes are placed outside the current bounds, the
 * first one landed 5px below the canvas edge and was simply invisible. Clicking
 * "Add Action" and seeing nothing happen is indistinguishable from a broken
 * button. Refitting on count (not on every change) leaves dragging alone, which
 * would otherwise fight the user's own panning.
 */
function FitOnLayoutChange({ signature }: { signature: string }) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    void fitView({ padding: 0.2, duration: 200 });
    // Keyed on node COUNT and ORIENTATION, not on every change: those are the
    // two things that move nodes outside the current viewport. Flipping
    // orientation re-lays the whole graph without changing the count, so a
    // count-only key left half the nodes off-canvas — refitting on every change
    // would instead fight the user's own panning mid-drag.
  }, [signature, fitView]);
  return null;
}

/** A one-line summary of a node's configuration, for the card body. */
const NODE_CHROME_PARAMS = new Set(["arity", "act_as"]);

function summarise(node: AutomationNode): string {
  const params = node.params as Record<string, unknown>;
  if (node.kind === NodeKind.trigger) {
    const parts = [String(params.event ?? "")];
    if (params.query) parts.push(String(params.query));
    return parts.filter(Boolean).join(" · ");
  }
  if (node.kind === NodeKind.filter) return String(params.slq ?? "") || "matches everything";
  if (node.kind === NodeKind.source) {
    const where = params.project ? ` in ${params.project}` : "";
    const query = String(params.slq ?? "");
    return query ? `${query}${where}` : "no query — finds nothing";
  }
  // A node has to say what IT tests. "event conditions" on every gate was the
  // same opacity as the abstract node these replaced.
  if (node.type === "gate.field_changed") {
    const side = (mode: unknown, values: unknown) =>
      mode === "specific" ? ((values as string[]) ?? []).join(" / ") || "…" :
      mode === "empty" ? "empty" : "any";
    return `${params.field ?? "?"}: ${side(params.from_mode, params.from_values)} → ${side(params.to_mode, params.to_values)}`;
  }
  if (node.type === "gate.changed_by") {
    const users = (params.users as string[]) ?? [];
    return `${params.negate ? "not " : ""}${users.join(", ") || "anyone"}`;
  }
  if (node.type === "gate.state_category") {
    return ((params.categories as string[]) ?? []).join(", ") || "any category";
  }
  if (node.type === "ai.classify") return String(params.prompt ?? "") || "ask a question…";
  if (node.kind === NodeKind.gate) return "event conditions";
  // The first param that says what the action DOES. `arity` and `act_as`
  // configure how it runs, not what it does, and either could sort first in a
  // stored params object — a card reading "arity: item" would be useless.
  const first = Object.entries(params).find(([key]) => !NODE_CHROME_PARAMS.has(key));
  return first ? `${first[0]}: ${String(first[1])}` : "";
}

export type Orientation = "vertical" | "horizontal";

interface GraphCanvasProps {
  nodes: AutomationNode[];
  edges: AutomationEdge[];
  onNodesChange?: (nodes: AutomationNode[]) => void;
  onConnect?: (edge: AutomationEdge) => void;
  onSelect?: (nodeId: string | null) => void;
  /** Nodes removed by React Flow's own delete key. Separate from
   * `onNodesChange` because a removal is not a move: it must also drop the
   * edges that touched the node, which only the graph owner can do. */
  onNodesDelete?: (nodeIds: string[]) => void;
  /** Edges removed by the delete key. */
  onEdgesDelete?: (edges: AutomationEdge[]) => void;
  /** Which way the graph flows. Ports, layout and edge curves all follow it. */
  orientation?: Orientation;
  /** Right-click on empty canvas — the Nuke-style add menu hangs off this. */
  onCanvasContextMenu?: (at: { x: number; y: number }) => void;
  /** Only for the arity badge: which node types fan out. Optional so the
   * read-only preview can render before the catalog resolves — a missing badge
   * is a smaller lie than a guessed one. */
  catalog?: AutomationCatalog;
  /** The last dry run, so each node can say what reached it and each port what
   * left. Null clears the annotations. */
  run?: RuleTestResult | null;
  /** No editing affordances — used for a branching automation until the full
   * editor lands, so it can at least be SEEN rather than refused outright. */
  readOnly?: boolean;
}

export default function GraphCanvas({
  nodes,
  edges,
  onNodesChange,
  onConnect,
  onSelect,
  onNodesDelete,
  onEdgesDelete,
  orientation = "vertical",
  onCanvasContextMenu,
  catalog,
  run,
  readOnly = false,
}: GraphCanvasProps) {
  /**
   * React Flow's own node state, seeded from the graph.
   *
   * Deriving these in a `useMemo` on every render was a real bug: React Flow
   * MEASURES each node and writes the result back through `onNodesChange`, and
   * keeps the node `visibility: hidden` until it has. Rebuilding the array from
   * scratch discarded that measurement every render, so the nodes stayed hidden
   * forever — present in the DOM, correctly positioned by getBoundingClientRect,
   * and invisible. Holding React Flow's state and re-seeding it only when the
   * GRAPH actually changes is what lets a measurement survive.
   */
  const build = useCallback(
    (): FlowNode[] =>
      layout(nodes, edges, orientation).map((placed) => ({
        id: placed.node.id,
        type: "radd",
        position: { x: placed.x, y: placed.y },
        data: {
          node: placed.node,
          subtitle: summarise(placed.node),
          orientation,
          // Blank unless the type offers a CHOICE: the badge means "there is a
          // decision here", which is information. On every node it would be
          // decoration.
          arity:
            arityOf(catalog, placed.node.type).options.length > 1
              ? effectiveArity(catalog, placed.node)
              : "",
          run: run?.nodes.find((entry) => entry.node_id === placed.node.id),
        } satisfies NodeData,
        draggable: !readOnly,
      })),
    [nodes, edges, readOnly, orientation, catalog, run],
  );

  const [flowNodes, setFlowNodes, onFlowNodesChange] = useNodesState<FlowNode>(build());

  //: Identity of the graph as DATA — not object identity, which changes on every
  //: parent render and would re-seed (and re-hide) the nodes continuously.
  const signature = useMemo(
    () =>
      JSON.stringify([
        orientation,
        // The catalog arrives AFTER the first render, and the arity badge is
        // built from it — without this the badges would be missing until
        // something else happened to change the graph. Same for a dry run,
        // which lands long after the graph is drawn.
        catalog?.node_arity?.length ?? 0,
        run?.nodes.map((n) => [n.node_id, n.ran, n.incoming, n.ports]) ?? null,
        nodes.map((n) => [n.id, n.type, n.params, n.x, n.y]),
      ]),
    [nodes, orientation, catalog, run],
  );
  useEffect(() => {
    setFlowNodes(build());
    // `build` is intentionally not a dependency: it changes identity with every
    // render, which is the very thing this effect exists to avoid reacting to.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, setFlowNodes]);

  const flowEdges = useMemo<FlowEdge[]>(
    () =>
      edges.map((edge, index) => ({
        id: `${edge.source}-${edge.port}-${edge.target}-${index}`,
        source: edge.source,
        sourceHandle: edge.port,
        target: edge.target,
        animated: false,
        style: { stroke: PORT_TONE[edge.port] ?? INLET_TONE, strokeWidth: 1.75 },
      })),
    [edges],
  );

  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      // Always let React Flow apply its own changes first — DIMENSION changes
      // live in here, and swallowing them is what kept every node hidden.
      onFlowNodesChange(changes as never);
      if (readOnly) return;

      // REMOVALS FIRST. React Flow owns the delete key, and applying a removal
      // only to its internal copy left the node in the graph — so the next
      // re-seed (adding any node changes the signature) resurrected it. That is
      // the difference the delete key and the inspector's Delete button had:
      // one went through the graph, the other did not.
      const removed = changes
        .filter((change) => change.type === "remove")
        .map((change) => (change as { id: string }).id);
      if (removed.length > 0 && onNodesDelete) {
        onNodesDelete(removed);
        return;
      }

      if (!onNodesChange) return;
      // Only report real movement upward; measurement and selection are React
      // Flow's business, and echoing them would re-seed the canvas mid-drag.
      const moved = changes.filter(
        (change) => change.type === "position" && change.dragging === false,
      );
      if (moved.length === 0) return;
      const positions = new Map(
        moved.map((change) => [
          (change as { id: string }).id,
          (change as { position?: { x: number; y: number } }).position,
        ]),
      );
      onNodesChange(
        nodes.map((node) => {
          const next = positions.get(node.id);
          return next ? { ...node, x: next.x, y: next.y } : node;
        }),
      );
    },
    [nodes, onNodesChange, onFlowNodesChange, readOnly],
  );

  const handleConnect = useCallback(
    (connection: Connection) => {
      if (readOnly || !onConnect || !connection.source || !connection.target) return;
      onConnect({
        source: connection.source,
        port: (connection.sourceHandle ?? "out") as AutomationEdge["port"],
        target: connection.target,
      });
    },
    [onConnect, readOnly],
  );

  return (
    <div className="h-[620px] w-full overflow-hidden rounded-[10px] border border-subtle bg-base">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onNodesChange={handleNodesChange}
        onEdgesChange={(changes) => {
          if (readOnly || !onEdgesDelete) return;
          // Same trap as nodes: an edge deleted by keyboard has to reach the
          // graph, or it comes back on the next re-seed.
          const gone = changes
            .filter((change) => change.type === "remove")
            .map((change) => flowEdges.find((e) => e.id === (change as { id: string }).id))
            .filter(Boolean)
            .map((edge) => ({
              source: edge!.source,
              port: (edge!.sourceHandle ?? "out") as AutomationEdge["port"],
              target: edge!.target,
            }));
          if (gone.length > 0) onEdgesDelete(gone);
        }}
        onConnect={handleConnect}
        onPaneContextMenu={(event) => {
          if (readOnly || !onCanvasContextMenu) return;
          event.preventDefault();
          const mouse = event as unknown as MouseEvent;
          onCanvasContextMenu({ x: mouse.clientX, y: mouse.clientY });
        }}
        onSelectionChange={({ nodes: picked }) => {
          // Only report a real user pick. React Flow fires this with [] while
          // reconciling a changed node list, and honouring that would clear the
          // selection we just set when a node was added.
          if (picked.length > 0) onSelect?.(picked[0].id);
        }}
        nodesConnectable={!readOnly}
        elementsSelectable
        fitView
        proOptions={{ hideAttribution: false }}
      >
        <FitOnLayoutChange signature={`${flowNodes.length}:${orientation}`} />
        <Background gap={18} size={1} color={GRID_TONE} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
