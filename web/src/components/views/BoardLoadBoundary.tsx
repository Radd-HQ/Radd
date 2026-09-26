import { useRef } from "react";
import { LoaderCircle } from "lucide-react";
import type { BoardLoading } from "../../lib/useBoardItems";
import { useNearViewport } from "../../lib/useNearViewport";
import { Button } from "../Button";

/** Intersection observes all clipping ancestors: an off-screen column or a
 * collapsed lane cannot start a fetch. Re-check after each batch fills space. */
export function BoardLoadBoundary({loading,column,lane}:{loading?:BoardLoading;column:string;lane?:string}) {
  const ref=useRef<HTMLDivElement>(null);
  const more=loading?.hasMore(column,lane)??false;
  const busy=loading?.loading(column,lane)??false;
  const failed=loading?.cellError(column,lane)??false;
  useNearViewport(ref,()=>loading?.load(column,lane),{margin:"200px",enabled:more&&!busy&&!failed});
  if(!loading || (!more&&!failed&&!busy)) return null;
  return <div ref={ref} data-board-loader className="flex min-h-10 shrink-0 items-center justify-center gap-2 py-2 text-xs text-fg-muted" role={failed?"alert":"status"}>
    {failed ? <Button size="sm" variant="secondary" onClick={()=>loading.load(column,lane)}>Retry loading</Button>
      : <><LoaderCircle size={14} className={busy?"animate-spin":""} aria-hidden />{busy?"Loading issues…":"Scroll to continue"}</>}
  </div>;
}
