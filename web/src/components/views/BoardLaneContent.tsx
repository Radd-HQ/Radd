import { useRef, useState, type ReactNode } from "react";
import { useNearViewport } from "../../lib/useNearViewport";

/** Keep complete lane headers available without mounting the whole matrix.
 * Once visited, a lane stays mounted so selections and drag targets survive. */
export function BoardLaneContent({children}:{children:()=>ReactNode}) {
  const ref=useRef<HTMLDivElement>(null);
  const [visited,setVisited]=useState(false);
  useNearViewport(ref,()=>setVisited(true),{margin:"200px",enabled:!visited});
  return <div ref={ref}>{visited?children():<div className="h-80" aria-label="Issues load when this lane is visible" />}</div>;
}
