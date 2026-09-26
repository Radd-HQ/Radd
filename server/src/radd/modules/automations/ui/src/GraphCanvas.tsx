/**
 * The automation node canvas. React Flow supplies pan/zoom/edges/hit-testing only; every node is ours,
 * in house tokens. Ports are colour-coded and ALWAYS visible (hover-revealed chrome is also invisible
 * to a CDP proof at baseline). Nodes without stored x/y are laid out by `automation-layout.ts`.
 */
import { useNodeShapes } from "./node-shapes";
import type { GraphCanvasProps } from "./canvas-contract";
import { shapeOf } from "./shape-contract";
import { useCapabilities } from "@radd/plugin-sdk";
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
import flowStyles from "@xyflow/react/dist/style.css?inline";
import canvasStyles from "./canvas.css?inline";
import {
  NodeKind,
  type AutomationEdge,
  type AutomationNode,
  type NodeResult,
  type Orientation,
} from "./types";
import { contributedPorts, nodeTitle, titleIndex } from "./automation-nodes";
import { arityOf, effectiveArity } from "./automation-outputs";
import {
  GRID_TONE,
  INLET_TONE,
  NODE_KIND_ICON,
  NODE_KIND_TONE,
  PORT_TONE,
  PORT_LABEL,
  VERDICT_VISUAL,
  portsOfNode,
} from "./node-visuals";
import { layout, NODE_WIDTH } from "./automation-layout";

interface NodeData extends Record<string, unknown> {
  node: AutomationNode;
  /** The type's palette label — what a person calls this node. */
  title: string;
  subtitle: string;
  orientation: Orientation;
  /** "item" when this node fans out; empty when the type offers no choice. */
  arity: string;
  /** Resolved where the catalog is in scope — a node inside React Flow's tree cannot ask. */
  ports: string[];
  portsAvailable: boolean;
  /** This node's last dry run, when there has been one. */
  run?: NodeResult;
  /** On a VALIDATE trigger: can anything it reaches refuse a submission? */
  validation?: "blocks" | "advises";
}

/** One node: kind icon, type, one-line summary. The detail panel says the rest. */
function GraphNode({ data, selected }: NodeProps) {
  const { node, title, subtitle, orientation, arity, ports, portsAvailable, run, validation } = data as NodeData;
  // Flow enters the top and leaves the bottom when vertical; left/right when
  // horizontal. Getting this wrong draws every edge as a sideways loop.
  const inletSide = orientation === "vertical" ? Position.Top : Position.Left;
  const outletSide = orientation === "vertical" ? Position.Bottom : Position.Right;
  const verdict = VERDICT_VISUAL[node.type];
  const Icon = verdict?.icon ?? NODE_KIND_ICON[node.kind];
  const tone = verdict?.tone ?? NODE_KIND_TONE[node.kind];

  return (
    <div
      style={{ width: NODE_WIDTH, ...(verdict ? { borderLeft: `3px solid ${verdict.tone}` } : {}) }}
      data-verdict={verdict ? node.type : undefined}
      className={`rounded-[10px] border bg-surface px-3 py-2.5 shadow-lift ${
        selected ? "border-emphasis outline outline-2 outline-offset-1 outline-focus" : "border-strong"
      }`}
      data-node-kind={node.kind}
      data-node-type={node.type}
      data-node-id={node.id}
    >
      {node.kind !== NodeKind.trigger && (
        <Handle type="target" isConnectable={portsAvailable} position={inletSide} style={{ background: INLET_TONE }} />
      )}
      <div className="flex items-center gap-1.5">
        <Icon size={13} className="shrink-0" style={{ color: tone }} aria-hidden />
        <span
          className="truncate text-[11px] uppercase tracking-wide"
          style={verdict ? { color: verdict.tone } : undefined}
        >
          <span className={verdict ? "" : "text-fg-muted"}>{verdict ? verdict.tag : node.kind}</span>
        </span>
        {validation && (
          <span
            data-validation-chip={validation}
            title={
              validation === "blocks"
                ? "A Block submission node is reachable: this can refuse a submission."
                : "Nothing reachable blocks: this only ever advises."
            }
            className="ml-auto shrink-0 rounded-[4px] border px-1 py-px text-[9px] uppercase tracking-wide"
            style={{
              color: validation === "blocks" ? "var(--status-danger-ink)" : "var(--status-warning-ink)",
              borderColor: validation === "blocks" ? "var(--status-danger-ink)" : "var(--status-warning-ink)",
            }}
          >
            {validation === "blocks" ? "Can block" : "Advisory only"}
          </span>
        )}
        {arity && (
          <span
            data-node-arity={arity}
            title={
              arity === "item"
                ? "Runs once for every issue that reaches it"
                : "Runs once, however many issues reach it"
            }
            className="ml-auto shrink-0 rounded-[4px] border border-subtle px-1 py-px text-[9px] uppercase tracking-wide text-fg-muted"
          >
            {arity === "item" ? "per issue" : "once"}
          </span>
        )}
      </div>
      <div className="mt-0.5 flex items-baseline gap-1.5">
        <span className="min-w-0 truncate text-[13px] font-medium text-heading" title={node.type}>{title}</span>
        {/* A producer's NAME, because it is what every downstream token says
            (spec 120) — reading a graph means knowing which node `triage` is. */}
        {node.name && (
          <code
            data-node-name={node.name}
            className="shrink-0 rounded-[4px] bg-elevated px-1 py-px text-[10px] text-accent-text"
          >
            {node.name}
          </code>
        )}
      </div>
      {subtitle && <div className="mt-0.5 truncate text-[11px] text-fg-secondary">{subtitle}</div>}
      {!portsAvailable && <div className="mt-1 text-[11px] text-fg-muted">Ports not resolved</div>}
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
          isConnectable={portsAvailable}
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
            // After a dry run a port shows what left it; a branch never emitted is struck through,
            // not "0" — "did not run" and "found nothing" are different answers.
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
                {PORT_LABEL[port] ?? port}
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

/** Refit when the node COUNT or ORIENTATION changes — the `fitView` prop only runs on mount, so an
 * added node landed off-canvas. Not on every change: that would fight the user's own panning. */
function FitOnLayoutChange({ signature }: { signature: string }) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    void fitView({ padding: 0.2, duration: 200 });
  }, [signature, fitView]);
  return null;
}

const NODE_CHROME_PARAMS = new Set(["arity", "act_as"]);

/** A one-line summary of a node's configuration, for the card body. */
function summarise(node: AutomationNode): string {
  const params = node.params as Record<string, unknown>;
  if (node.kind === NodeKind.trigger) return String(params.event ?? "");
  if (node.type === "filter.slq") return String(params.slq ?? "") || "matches everything";
  if (node.type === "search.slq") {
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
  if (node.type === "gate.comment") {
    const thread = params.thread === "reply" ? "a reply" : params.thread === "root" ? "a thread root" : "any comment";
    const visibility = params.visibility === "internal" || params.visibility === "public" ? `, ${params.visibility}` : "";
    return `${thread}${visibility}`;
  }
  if (node.type === "gate.page_space") {
    const spaces = (params.spaces as string[]) ?? [];
    return `${params.negate ? "not in " : "in "}${spaces.join(", ") || "…"}`;
  }
  if (node.type === "gate.project") {
    const projects = (params.projects as string[]) ?? [];
    return `${params.negate ? "not " : ""}${projects.join(", ") || "…"}`;
  }
  if (node.type === "gate.payload") {
    const value = Array.isArray(params.value) ? (params.value as string[]).join(", ") : String(params.value ?? "");
    return `${params.negate ? "not " : ""}${params.path || "…"} ${params.operator ?? "eq"} ${value}`.trim();
  }
  // The first param that says what the node DOES: skip `arity`/`act_as` (how it runs), blanks and
  // non-scalars ("include: [object Object]").
  const first = Object.entries(params).find(
    ([key, value]) =>
      !NODE_CHROME_PARAMS.has(key) &&
      (value === null || typeof value !== "object") &&
      String(value ?? "").trim() !== "",
  );
  return first ? `${first[0]}: ${String(first[1])}` : "";
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
  validationChips,
  shapes: suppliedShapes,
}: GraphCanvasProps) {
  const capabilities = useCapabilities();
  // Static ports per contributed type, from the catalog (empty until it resolves).
  const declaredPorts = useMemo(() => contributedPorts(catalog), [catalog]);
  // Server-computed shapes for params-dependent nodes.
  const resolvedShapes = useNodeShapes(nodes, catalog, suppliedShapes === undefined);
  const shapes = suppliedShapes ?? resolvedShapes;
  const portsAvailable = (node: AutomationNode) => {
    if (node.kind === NodeKind.trigger) return true;
    const spec = catalog?.nodes.find(entry => entry.key === node.type);
    return Boolean(spec && (!spec.plugin || capabilities?.plugins.includes(spec.plugin))
      && (!spec.dynamic_ports || shapeOf(node, shapes)));
  };
  const titles = useMemo(() => titleIndex(catalog), [catalog]);
  const build = useCallback(
    (): FlowNode[] =>
      layout(nodes, edges, orientation).map((placed) => ({
        id: placed.node.id,
        type: "radd",
        position: { x: placed.x, y: placed.y },
        data: {
          node: placed.node,
          title: nodeTitle(placed.node, titles),
          subtitle: summarise(placed.node),
          orientation,
          // Only when the type offers a CHOICE — otherwise it is decoration.
          arity:
            arityOf(catalog, placed.node.type).options.length > 1
              ? effectiveArity(catalog, placed.node)
              : "",
          // Preserve existing wires while a shape/provider is unavailable, but
          // do not invent connectable handles from the node kind's defaults.
          ports: portsAvailable(placed.node)
            ? portsOfNode(placed.node, declaredPorts, shapes)
            : [...new Set(edges.filter(edge => edge.source === placed.node.id).map(edge => edge.port))],
          portsAvailable: portsAvailable(placed.node),
          validation: validationChips?.[placed.node.id],
          run: run?.nodes.find((entry) => entry.node_id === placed.node.id),
        } satisfies NodeData,
        draggable: !readOnly,
      })),
    [nodes, edges, readOnly, orientation, catalog, declaredPorts, titles, run, validationChips, shapes, capabilities],
  );

  // React Flow MEASURES each node and writes it back through onNodesChange, keeping it hidden until then;
  // rebuilding the array every render discarded that, so nodes stayed invisible. Hold React Flow's state
  // and re-seed only when the graph's DATA changes (`signature`).
  const [flowNodes, setFlowNodes, onFlowNodesChange] = useNodesState<FlowNode>(build());

  //: Identity of the graph as DATA — not object identity, which changes on every
  //: parent render and would re-seed (and re-hide) the nodes continuously.
  const signature = useMemo(
    () =>
      JSON.stringify([
        orientation,
        // Content, not counts: plugin withdrawal or replacement can retain the
        // same number of entries while changing labels, ports, or arity.
        catalog,
        capabilities?.plugins,
        readOnly,
        shapes,
        run?.nodes ?? null,
        // Chips depend on what a trigger REACHES, which is not in the node list.
        validationChips ?? null,
        edges.map((e) => [e.source, e.port, e.target]),
        nodes.map((n) => [n.id, n.type, n.name, n.params, n.x, n.y]),
      ]),
    [nodes, edges, orientation, catalog, run, validationChips, shapes, readOnly, capabilities],
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

      // REMOVALS FIRST: React Flow owns the delete key, and a removal applied only to its copy was
      // resurrected by the next re-seed.
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
    [nodes, onNodesChange, onNodesDelete, onFlowNodesChange, readOnly],
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
    <div className="radd-automation-canvas h-[620px] w-full overflow-hidden rounded-[10px] border border-subtle bg-base">
      <style>{flowStyles + canvasStyles}</style>
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
        deleteKeyCode={readOnly ? null : ["Backspace", "Delete"]}
        elementsSelectable
        fitView
      >
        <FitOnLayoutChange signature={`${flowNodes.length}:${orientation}`} />
        <Background gap={18} size={1} color={GRID_TONE} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
