/**
 * The automation editor (spec 116, RADD-916): node panel, canvas, inspector.
 *
 * There is no form view any more. The graph expresses everything the list did,
 * and keeping both meant a `toLinear`/`toGraph` adapter, a second source of
 * truth, and a "this branches so the form is unavailable" special case — all of
 * which existed only to hold two editors in step.
 *
 * Nodes are added two ways, both reading ONE catalogue so they cannot disagree:
 * click a row in the panel, or right-click the canvas and search (Nuke's tab
 * menu). Everything is a node, triggers included — a graph fires only for the
 * triggers it actually contains, and it may contain several.
 */
import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowRight } from "lucide-react";
import { automationCatalogQuery } from "../../lib/queries";
import { instantiate, nodeTemplates, type NodeTemplate } from "../../lib/automation-nodes";
import { layout, NODE_HEIGHT, NODE_WIDTH } from "../../lib/automation-layout";
import {
  NodeKind,
  type AutomationEdge,
  type AutomationNode,
  type RuleTestResult,
} from "../../lib/types";
import { Callout, CalloutKind } from "../Callout";
import { usePickerData } from "./ActionsBuilder";
import { GraphInspector } from "./GraphInspector";
import { LazyGraphCanvas } from "./LazyGraphCanvas";
import { NodePanel } from "./NodePanel";
import { NodeSearchMenu } from "./NodeSearchMenu";

export type Orientation = "vertical" | "horizontal";

interface GraphEditorProps {
  nodes: AutomationNode[];
  edges: AutomationEdge[];
  orientation: Orientation;
  onChange: (graph: { nodes: AutomationNode[]; edges: AutomationEdge[] }) => void;
  onOrientationChange: (orientation: Orientation) => void;
  /** The last dry run, annotated onto the canvas: what reached each node and
   * what left each port. Owned by the page, because the panel that produces it
   * sits outside the editor. */
  run?: RuleTestResult | null;
}

export function GraphEditor({
  nodes,
  edges,
  orientation,
  onChange,
  onOrientationChange,
  run,
}: GraphEditorProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [menuAt, setMenuAt] = useState<{ x: number; y: number } | null>(null);
  const pickers = usePickerData();
  const catalog = useQuery(automationCatalogQuery);
  const templates = useMemo(() => nodeTemplates(catalog.data), [catalog.data]);
  // What the "field changed" picker offers. Builtins the event diff actually
  // reports, plus every custom field key — a field the diff never names would
  // be a condition that can only ever be false.
  const fieldNames = useMemo(
    () => [
      "state", "priority", "assignee", "team", "cycle", "release", "title",
      "description", "start_date", "target_date", "estimate_points", "parent",
      ...(pickers.fields ?? []).map((field) => `cf.${field.key}`),
    ],
    [pickers.fields],
  );
  const valueSuggestions = useMemo(
    () => [...(pickers.stateNames ?? []), ...(pickers.labelNames ?? []), "low", "normal", "high", "blocker"],
    [pickers.stateNames, pickers.labelNames],
  );
  const selected = useMemo(() => nodes.find((n) => n.id === selectedId) ?? null, [nodes, selectedId]);

  /**
   * Which triggers can reach the selected node, merged into one shape for the
   * condition builder.
   *
   * A gate fed by two different events has no single trigger, so a subject is
   * offered when ANY upstream trigger can supply it — offering only what they
   * all share would hide a legitimate condition, and offering everything would
   * let someone write a change-subject test against a trigger that carries no
   * diff.
   */
  const upstreamTrigger = useMemo(() => {
    if (!selected || !catalog.data) return undefined;
    const incoming = new Map<string, string[]>();
    for (const edge of edges) incoming.set(edge.target, [...(incoming.get(edge.target) ?? []), edge.source]);
    const seen = new Set<string>();
    const queue = [selected.id];
    const events: string[] = [];
    while (queue.length) {
      const id = queue.pop() as string;
      if (seen.has(id)) continue;
      seen.add(id);
      const node = nodes.find((n) => n.id === id);
      if (node?.kind === NodeKind.trigger) events.push(String(node.params.event ?? ""));
      queue.push(...(incoming.get(id) ?? []));
    }
    const infos = catalog.data.triggers.filter((t) => events.includes(t.event_type));
    if (infos.length === 0) return undefined;
    if (infos.length === 1) return infos[0];
    return {
      ...infos[0],
      label: `${infos.length} triggers`,
      item_scoped: infos.some((t) => t.item_scoped),
      has_changes: infos.some((t) => t.has_changes),
    };
  }, [selected, nodes, edges, catalog.data]);

  const addTemplate = useCallback(
    (template: NodeTemplate) => {
      // Placed beyond the current extent along the flow axis. Measured from the
      // LAID-OUT positions, not from stored x/y: a node that has never been
      // dragged has no coordinates, so reading them gives 0 and the new node
      // lands on top of an auto-placed one — which is exactly what happened.
      const placed = layout(nodes, edges, orientation);
      const far = placed.reduce(
        (max, p) => Math.max(max, orientation === "vertical" ? p.y : p.x),
        0,
      );
      const at =
        orientation === "vertical"
          ? { x: 0, y: far + NODE_HEIGHT + 70 }
          : { x: far + NODE_WIDTH + 90, y: 0 };
      const node = instantiate(template, nodes, at);
      onChange({ nodes: [...nodes, node], edges });
      setSelectedId(node.id);
      setMenuAt(null);
    },
    [nodes, edges, orientation, onChange],
  );

  const updateNode = useCallback(
    (next: AutomationNode) =>
      onChange({ nodes: nodes.map((n) => (n.id === next.id ? next : n)), edges }),
    [nodes, edges, onChange],
  );

  const deleteNodes = useCallback(
    (nodeIds: string[]) => {
      const gone = new Set(nodeIds);
      onChange({
        nodes: nodes.filter((n) => !gone.has(n.id)),
        edges: edges.filter((e) => !gone.has(e.source) && !gone.has(e.target)),
      });
      setSelectedId((current) => (current && gone.has(current) ? null : current));
    },
    [nodes, edges, onChange],
  );

  const deleteEdges = useCallback(
    (removed: AutomationEdge[]) => {
      const key = (e: AutomationEdge) => `${e.source}|${e.port}|${e.target}`;
      const gone = new Set(removed.map(key));
      onChange({ nodes, edges: edges.filter((e) => !gone.has(key(e))) });
    },
    [nodes, edges, onChange],
  );

  const deleteNode = useCallback(
    (nodeId: string) => {
      // Edges touching a deleted node go with it — leaving them would be a graph
      // the server rejects ("edge to unknown node"), i.e. an automation nobody
      // can save and no message explaining why.
      onChange({
        nodes: nodes.filter((n) => n.id !== nodeId),
        edges: edges.filter((e) => e.source !== nodeId && e.target !== nodeId),
      });
      setSelectedId(null);
    },
    [nodes, edges, onChange],
  );

  const connect = useCallback(
    (edge: AutomationEdge) => {
      if (
        edges.some(
          (e) => e.source === edge.source && e.port === edge.port && e.target === edge.target,
        )
      ) {
        return;
      }
      // One edge per (source, port): re-dragging a port MOVES the connection
      // rather than silently fanning out, which is what a filter's two ports
      // lead people to expect.
      const replaced = edges.filter((e) => !(e.source === edge.source && e.port === edge.port));
      onChange({ nodes, edges: [...replaced, edge] });
    },
    [nodes, edges, onChange],
  );

  const moveNodes = useCallback(
    (next: AutomationNode[]) => onChange({ nodes: next, edges }),
    [edges, onChange],
  );

  const triggers = useMemo(() => nodes.filter((n) => n.kind === NodeKind.trigger), [nodes]);

  /** Does ANY trigger resolve a target item? Item tokens are blank without one,
   * and the reference says so rather than letting someone build a title around
   * a value their trigger never supplies. */
  const triggersResolveAnItem = useMemo(() => {
    const scoped = new Set(
      (catalog.data?.triggers ?? []).filter((t) => t.item_scoped).map((t) => t.event_type),
    );
    return triggers.some((t) => scoped.has(String(t.params.event ?? "")));
  }, [triggers, catalog.data]);

  /** Nodes no trigger can reach. They are stored and valid, they simply never
   * run — the quietest way for an automation to do nothing, so it is said. */
  const unreachable = useMemo(() => {
    const reached = new Set(triggers.map((t) => t.id));
    let grew = true;
    while (grew) {
      grew = false;
      for (const edge of edges) {
        if (reached.has(edge.source) && !reached.has(edge.target)) {
          reached.add(edge.target);
          grew = true;
        }
      }
    }
    return nodes.filter((n) => !reached.has(n.id)).map((n) => n.id);
  }, [nodes, edges, triggers]);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-fg-secondary">
          {triggers.length === 0
            ? "No trigger yet — add one from the panel, or right-click the canvas."
            : `Runs on ${triggers.length} trigger${triggers.length === 1 ? "" : "s"}.`}
        </p>
        <div className="inline-flex rounded-[8px] border border-subtle p-0.5">
          {[
            { key: "vertical" as const, label: "Vertical", Icon: ArrowDown },
            { key: "horizontal" as const, label: "Horizontal", Icon: ArrowRight },
          ].map(({ key, label, Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => onOrientationChange(key)}
              aria-pressed={orientation === key}
              title={`${label} flow`}
              className={`inline-flex items-center gap-1 rounded-[6px] px-2 py-1 text-xs cursor-pointer ${
                orientation === key ? "bg-accent text-black" : "text-fg-secondary hover:text-heading"
              }`}
            >
              <Icon size={12} aria-hidden />
              {label}
            </button>
          ))}
        </div>
      </div>

      {triggers.length === 0 && nodes.length > 0 && (
        <Callout kind={CalloutKind.warning}>
          This automation has no trigger, so nothing will ever start it. Add one from the panel — it
          saves either way, so you can finish wiring later.
        </Callout>
      )}
      {unreachable.length > 0 && (
        <Callout kind={CalloutKind.warning}>
          No trigger reaches <strong className="font-medium">{unreachable.join(", ")}</strong>, so{" "}
          {unreachable.length === 1 ? "it" : "they"} will never run. Drag from a port to connect.
        </Callout>
      )}

      <div className="flex gap-3">
        <NodePanel templates={templates} onAdd={addTemplate} />
        <div className="min-w-0 flex-1">
          <LazyGraphCanvas
            nodes={nodes}
            edges={edges}
            orientation={orientation}
            onNodesChange={moveNodes}
            onConnect={connect}
            onSelect={setSelectedId}
            onNodesDelete={deleteNodes}
            onEdgesDelete={deleteEdges}
            onCanvasContextMenu={setMenuAt}
            catalog={catalog.data}
            run={run}
          />
        </div>
        <div className="w-[380px] shrink-0">
          <GraphInspector
            node={selected}
            nodes={nodes}
            edges={edges}
            pickers={pickers}
            catalog={catalog.data}
            trigger={upstreamTrigger}
            fieldNames={fieldNames}
            valueSuggestions={valueSuggestions}
            canActAs={catalog.data?.can_act_as ?? false}
            hasItem={triggersResolveAnItem}
            onChange={updateNode}
            onDelete={deleteNode}
          />
        </div>
      </div>

      {menuAt && (
        <NodeSearchMenu
          templates={templates}
          at={menuAt}
          onPick={addTemplate}
          onClose={() => setMenuAt(null)}
        />
      )}
    </div>
  );
}
