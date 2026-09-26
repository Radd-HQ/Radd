import { lazy, Suspense } from "react";
import type { GraphCanvasProps } from "./canvas-contract";
const GraphCanvas = lazy(() => import("./GraphCanvas"));
export function LazyGraphCanvas(props: GraphCanvasProps) {
  return <Suspense fallback={<p>Loading canvas…</p>}><GraphCanvas {...props} /></Suspense>;
}
