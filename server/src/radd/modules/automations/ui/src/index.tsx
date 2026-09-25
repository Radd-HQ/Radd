import { lazy, Suspense } from "react";
import { definePlugin } from "@radd/plugin-sdk";
import { GRAPH_CANVAS_SLOT, type GraphCanvasProps } from "./canvas-contract";

const GraphCanvas = lazy(() => import("./GraphCanvas"));
export default definePlugin({ contributions: [{
  id: "graph-canvas", slot: GRAPH_CANVAS_SLOT, toggleable: false,
  render: props => <Suspense fallback={<div className="h-[620px] border border-subtle p-4">Loading canvas…</div>}>
    <GraphCanvas {...(props as unknown as GraphCanvasProps)} />
  </Suspense>,
}] });
