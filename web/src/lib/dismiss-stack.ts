/**
 * Escape-dismiss stack: every overlay (modal, peek panel) registers its close
 * handler on mount, and ONE document listener dismisses only the TOPMOST
 * overlay per Esc press. Without this each overlay listens on `document`
 * independently, so Esc over a peek-above-a-modal closes BOTH — discarding the
 * half-typed draft the peek existed to protect.
 *
 * The top handler returns whether it consumed the event (false = "I'm guarding
 * an editing surface"); an unconsumed Esc never falls through to overlays
 * underneath — they are just as buried as the top one.
 */

type DismissHandler = (event: KeyboardEvent) => boolean;

const stack: DismissHandler[] = [];

function onKeyDown(event: KeyboardEvent) {
  if (event.key !== "Escape") return;
  const top = stack[stack.length - 1];
  if (top) top(event);
}

/** Register an overlay's Esc handler; returns the unregister cleanup. */
export function registerDismiss(handler: DismissHandler): () => void {
  if (stack.length === 0) document.addEventListener("keydown", onKeyDown);
  stack.push(handler);
  return () => {
    const index = stack.lastIndexOf(handler);
    if (index !== -1) stack.splice(index, 1);
    if (stack.length === 0) document.removeEventListener("keydown", onKeyDown);
  };
}
