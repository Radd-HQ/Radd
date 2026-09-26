import { useEffect, useRef, type RefObject } from "react";

/**
 * Calls `onNear` whenever `ref`'s element is within `margin` of the viewport. IntersectionObserver
 * respects every clipping ancestor, so an off-screen column or a collapsed lane never counts. The
 * observer is rebuilt when `enabled` flips, and a fresh observer reports at once — which is how a
 * caller re-checks after its own state changed (a batch that did not fill the space).
 */
export function useNearViewport(
  ref: RefObject<Element | null>,
  onNear: () => void,
  { margin, enabled = true }: { margin: string; enabled?: boolean },
): void {
  const onNearRef = useRef(onNear);
  onNearRef.current = onNear;
  useEffect(() => {
    const node = ref.current;
    if (!node || !enabled) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) onNearRef.current();
      },
      { rootMargin: margin },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref, enabled, margin]);
}
