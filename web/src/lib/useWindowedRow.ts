import { useEffect, useRef, useState, type RefObject } from "react";

/**
 * Whether a list row is close enough to the viewport to be worth mounting
 * (RADD-1565).
 *
 * A 200-row page mounted every row's cells: about 10,700 DOM nodes for a
 * screen that shows fifteen rows. The row's own element always exists, so
 * focus order, selection, drag targets and the scroll height are unchanged;
 * what this decides is whether its CELLS are rendered. A row that leaves keeps
 * the height it measured, so the page does not move under the reader.
 *
 * One observer per scrolling container, shared by its rows: an observer per
 * row is two hundred observers. The container has to be the observer's ROOT,
 * because a margin only extends the root: against the viewport, a row inside
 * the list's own scroller is clipped by it and reports "near" only once it is
 * already on screen, which shows as rows filling in under the reader.
 */
const MARGIN = "900px 0px";

type Listener = (near: boolean) => void;
const listeners = new WeakMap<Element, Listener>();
const observers = new WeakMap<Element, IntersectionObserver>();
let viewportObserver: IntersectionObserver | null = null;

function scroller(node: Element): Element | null {
  for (let parent = node.parentElement; parent; parent = parent.parentElement) {
    const overflow = getComputedStyle(parent).overflowY;
    if (overflow === "auto" || overflow === "scroll") return parent;
  }
  return null;
}

function observerFor(node: Element): IntersectionObserver | null {
  if (typeof IntersectionObserver === "undefined") return null;
  const report: IntersectionObserverCallback = (entries) => {
    for (const entry of entries) listeners.get(entry.target)?.(entry.isIntersecting);
  };
  const root = scroller(node);
  if (!root) return (viewportObserver ??= new IntersectionObserver(report, { rootMargin: MARGIN }));
  let found = observers.get(root);
  if (!found) {
    found = new IntersectionObserver(report, { root, rootMargin: MARGIN });
    observers.set(root, found);
  }
  return found;
}

export function useWindowedRow<T extends HTMLElement>(
  eager: boolean,
): { ref: RefObject<T | null>; near: boolean; reserved: number | undefined } {
  const ref = useRef<T | null>(null);
  // Without an observer (an old browser, a test renderer) every row is mounted.
  const [near, setNear] = useState(eager || typeof IntersectionObserver === "undefined");
  const reserved = useRef<number | undefined>(undefined);
  useEffect(() => {
    const node = ref.current;
    const watch = node ? observerFor(node) : null;
    if (!node || !watch) return;
    listeners.set(node, (isNear) => {
      // Leaving: remember how tall the real row was before its cells go.
      if (!isNear) reserved.current = node.offsetHeight;
      setNear(isNear);
    });
    watch.observe(node);
    return () => {
      watch.unobserve(node);
      listeners.delete(node);
    };
  }, []);
  return { ref, near, reserved: near ? undefined : reserved.current };
}
