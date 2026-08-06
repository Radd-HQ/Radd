/**
 * The canvas, code-split (spec 116 decision).
 *
 * React Flow has no business loading for someone editing a board — the SPA
 * bundle already warns past 500 kB, and the canvas is reachable from exactly one
 * settings page. `lazy` keeps it in its own chunk that arrives when the Graph
 * tab is opened.
 */
import { Suspense, lazy } from "react";
import type { ComponentProps } from "react";

const GraphCanvas = lazy(() => import("./GraphCanvas"));

export function LazyGraphCanvas(props: ComponentProps<typeof GraphCanvas>) {
  return (
    <Suspense
      fallback={
        <div className="flex h-[620px] w-full items-center justify-center rounded-[10px] border border-subtle bg-base text-xs text-fg-muted">
          Loading canvas…
        </div>
      }
    >
      <GraphCanvas {...props} />
    </Suspense>
  );
}
