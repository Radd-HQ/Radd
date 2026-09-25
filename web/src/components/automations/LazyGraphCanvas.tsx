/** Transitional editor adapter. Automations contributes and owns the renderer. */
import { Slot } from "@radd/plugin-sdk";
import { GRAPH_CANVAS_SLOT, type GraphCanvasProps } from "../../../../server/src/radd/modules/automations/ui/src/canvas-contract";

export function LazyGraphCanvas(props: GraphCanvasProps) {
  const unavailable = <div role="status" className="flex h-[620px] items-center justify-center rounded-[10px] border border-subtle bg-base text-sm text-fg-muted">
    Automation canvas unavailable. Your graph is preserved.
  </div>;
  return <Slot id={GRAPH_CANVAS_SLOT} {...props} fallback={unavailable} errorFallback={unavailable} />;
}
