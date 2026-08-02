/** Cycle-series naming helpers — the frontend twin of the backend's
 * `cycles/types.py` (keep in lockstep): a cycle belongs to a series by NAME,
 * label + trailing number ("PIPE - 115" and "PIPE-114" are both label "PIPE"). */

const NUMBERED_NAME_RE = /^(.*?)[\s\-–—_]*(\d+)\s*$/;

export function parseCycleName(name: string): { label: string; number: number } | null {
  const match = NUMBERED_NAME_RE.exec(name);
  if (!match || !match[1]) return null;
  return { label: match[1], number: Number(match[2]) };
}

export function cycleLabel(name: string): string | null {
  return parseCycleName(name)?.label ?? null;
}

export function sameLabel(a: string | null, b: string | null): boolean {
  return a !== null && b !== null && a.toLowerCase() === b.toLowerCase();
}

/** Weekday labels indexed by the backend's Python convention: 0 = Monday. */
export const WEEKDAY_LABELS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;
