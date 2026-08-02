import type { PointerEvent as ReactPointerEvent } from "react";

export interface HorizontalDragOptions {
  start: number;
  min: number;
  max: number;
  /** +1 (default): the value grows as the pointer moves right; -1: left. */
  direction?: 1 | -1;
  /** Fires per pointer move with the clamped value — drive live state here. */
  onMove: (value: number) => void;
  /** Fires once on release with the final value — persist here, not per move. */
  onEnd?: (value: number) => void;
}

/**
 * Shared pointer-drag-to-resize (spec 108 — extracted from the roadmap label
 * gutter and the peek drawer, which had copy-pasted it): window-level
 * listeners so the drag survives leaving the handle, clamped to [min, max],
 * persistence deferred to release.
 */
export function startHorizontalDrag(
  event: ReactPointerEvent,
  options: HorizontalDragOptions,
): void {
  event.preventDefault();
  const startX = event.clientX;
  const direction = options.direction ?? 1;
  let value = options.start;
  const move = (pointer: PointerEvent) => {
    value = Math.min(
      options.max,
      Math.max(options.min, options.start + direction * (pointer.clientX - startX)),
    );
    options.onMove(value);
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    options.onEnd?.(value);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up, { once: true });
}
