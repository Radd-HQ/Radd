import { useLayoutEffect, useRef, type ReactNode } from "react";
import { Button } from "./Button";

/** Keep the first visible comment at the same screen position when older rows
 * prepend. Browser scroll anchoring is disabled here so it cannot double-adjust. */
export function CommentHistory({ children, hasOlder, loading, onOlder, error }: {
  children: ReactNode; hasOlder: boolean; loading: boolean;
  onOlder: () => unknown; error?: string;
}) {
  const root = useRef<HTMLDivElement>(null);
  const anchor = useRef<{ element: Element; top: number } | null>(null);
  useLayoutEffect(() => {
    if (loading || !anchor.current) return;
    const { element, top } = anchor.current;
    if (!element.isConnected) { anchor.current = null; return; }
    let scroller = root.current?.parentElement;
    while (scroller && !/(auto|scroll)/.test(getComputedStyle(scroller).overflowY)) {
      scroller = scroller.parentElement;
    }
    const restore = () => {
      if (!anchor.current || !element.isConnected) return;
      const delta = element.getBoundingClientRect().top - top;
      if (scroller) scroller.scrollTo({ top: scroller.scrollTop + delta, behavior: "instant" });
      else window.scrollBy({ top: delta, behavior: "instant" });
    };
    restore();
    if (!hasOlder && element instanceof HTMLElement) {
      element.tabIndex = -1;
      element.focus({ preventScroll: true });
    }
    // Lazy viewers/images may settle after the page arrives. Keep the anchor
    // until the reader acts, then immediately stop adjusting their scroll.
    const observer = new ResizeObserver(restore);
    if (root.current) observer.observe(root.current);
    const release = () => { anchor.current = null; observer.disconnect(); };
    for (const type of ["wheel", "touchstart", "pointerdown", "keydown"]) {
      document.addEventListener(type, release, { passive: true, capture: true });
    }
    return () => {
      observer.disconnect();
      for (const type of ["wheel", "touchstart", "pointerdown", "keydown"]) {
        document.removeEventListener(type, release, { capture: true });
      }
    };
  }, [loading, children, hasOlder]);
  return <div ref={root} className="flex flex-col gap-3 [overflow-anchor:none]">
    {hasOlder && <Button size="sm" variant="secondary" disabled={loading} onClick={() => {
      const element = Array.from(root.current?.querySelectorAll("[data-comment-id]") ?? [])
        .find(row => row.getBoundingClientRect().bottom > 0);
      if (element) anchor.current = { element, top: element.getBoundingClientRect().top };
      onOlder();
    }}>{loading ? "Loading older comments…" : "Load older comments"}</Button>}
    {error && <p role="alert" className="text-xs text-status-danger-ink">{error}</p>}
    {children}
  </div>;
}
