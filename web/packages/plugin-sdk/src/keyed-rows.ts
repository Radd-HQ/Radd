import { useRef } from "react";

let counter = 0;
/** Monotonic per-session key — no crypto needed for render identity. */
function mintKey(): string {
  counter += 1;
  return `row-${counter}`;
}

/**
 * Stable render keys for removable row builders (RADD-901). Eight builders
 * keyed editable rows by `key={index}`, so deleting row N re-keyed every row
 * below it — focus lost, editor state flashed. This mints an id per row at
 * ADD time and retires it at REMOVE time, so surviving rows keep their key
 * (and their DOM) across removals.
 *
 * Route every insert through `add` and every removal through `removeAt`;
 * in-place edits (`rows[i] = …` via onChange) need nothing. A wholesale
 * external replacement (loading a saved rule, reset) is reconciled by length
 * — extras get fresh keys, leftovers are dropped from the tail — which is
 * exactly right for load/reset and the documented limit of this helper:
 * an external REMOVAL that bypasses `removeAt` would retire the wrong key.
 */
export function useKeyedRows<T>(rows: readonly T[], onChange: (next: T[]) => void) {
  const keysRef = useRef<string[]>([]);
  if (keysRef.current.length !== rows.length) {
    const next = keysRef.current.slice(0, rows.length);
    while (next.length < rows.length) next.push(mintKey());
    keysRef.current = next;
  }

  const add = (row: T, index: number = rows.length) => {
    keysRef.current = [
      ...keysRef.current.slice(0, index),
      mintKey(),
      ...keysRef.current.slice(index),
    ];
    onChange([...rows.slice(0, index), row, ...rows.slice(index)]);
  };

  const removeAt = (index: number) => {
    keysRef.current = keysRef.current.filter((_, i) => i !== index);
    onChange(rows.filter((_, i) => i !== index));
  };

  /** Reorder mirror: the key travels WITH its row, so the moved row keeps its DOM. */
  const swap = (a: number, b: number) => {
    if (a < 0 || b < 0 || a >= rows.length || b >= rows.length) return;
    const nextKeys = [...keysRef.current];
    [nextKeys[a], nextKeys[b]] = [nextKeys[b], nextKeys[a]];
    keysRef.current = nextKeys;
    const next = [...rows];
    [next[a], next[b]] = [next[b], next[a]];
    onChange(next);
  };

  return { keys: keysRef.current, add, removeAt, swap };
}
