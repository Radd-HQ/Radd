import { useEffect, useLayoutEffect, useState, type RefObject } from "react";

/** Clearance a floating panel keeps from every viewport edge. */
const VIEWPORT_MARGIN_PX = 8;
/** Gap between an anchored card and the element it describes. */
const CARD_GAP_PX = 8;

/**
 * A `fixed` panel opened at a point (a right-click, a drop): rendered at the raw
 * point, clamped into the viewport pre-paint once measurable, and closed by an
 * outside pointerdown, Escape, scroll or resize.
 */
export function usePointAnchoredPanel(
  rootRef: RefObject<HTMLElement | null>,
  x: number,
  y: number,
  onClose: () => void,
): { left: number; top: number } {
  const [pos, setPos] = useState({ left: x, top: y });

  useLayoutEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const left = Math.min(x, window.innerWidth - rect.width - VIEWPORT_MARGIN_PX);
    const top = Math.min(y, window.innerHeight - rect.height - VIEWPORT_MARGIN_PX);
    setPos({ left: Math.max(VIEWPORT_MARGIN_PX, left), top: Math.max(VIEWPORT_MARGIN_PX, top) });
  }, [rootRef, x, y]);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onClose, true);
    window.addEventListener("resize", onClose);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onClose, true);
      window.removeEventListener("resize", onClose);
    };
  }, [rootRef, onClose]);

  return pos;
}

/** The viewport box a hover card hangs from. */
export interface CardAnchor {
  left: number;
  top: number;
  bottom: number;
}

/**
 * A `fixed` hover card below `anchor`, flipped above when the viewport bottom is
 * near and clamped inside the viewport. It renders at the raw anchor, then
 * corrects pre-paint once its size is measurable; `deps` re-run the correction
 * when the card's content (and so its height) changes.
 */
export function useAnchoredCardPosition(
  rootRef: RefObject<HTMLElement | null>,
  anchor: CardAnchor,
  deps: readonly unknown[] = [],
): { left: number; top: number } {
  const [pos, setPos] = useState({ left: anchor.left, top: anchor.bottom + CARD_GAP_PX });

  useLayoutEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    let top = anchor.bottom + CARD_GAP_PX;
    if (top + rect.height > window.innerHeight - VIEWPORT_MARGIN_PX) {
      top = anchor.top - rect.height - CARD_GAP_PX;
    }
    top = Math.max(
      VIEWPORT_MARGIN_PX,
      Math.min(top, window.innerHeight - rect.height - VIEWPORT_MARGIN_PX),
    );
    const left = Math.max(
      VIEWPORT_MARGIN_PX,
      Math.min(anchor.left, window.innerWidth - rect.width - VIEWPORT_MARGIN_PX),
    );
    setPos({ left, top });
  }, [rootRef, anchor, ...deps]);

  return pos;
}
