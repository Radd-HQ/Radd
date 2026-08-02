/**
 * Text-quote anchoring for inline comments (RADD-726/728).
 *
 * An anchor is `{quote, prefix, suffix}` — the selected text plus a little
 * context either side — and NOT a character offset. An offset is invalidated by
 * the first edit made anywhere above it, so inserting one paragraph would slide
 * every comment on the page onto the wrong sentence. A quote is re-located
 * against the current text on every render, which is why W3C Web Annotation and
 * every editor that survives concurrent editing stores one.
 *
 * These functions live on the CLIENT and only here, deliberately. Re-location
 * needs the text as RENDERED — the server stores the anchor and never resolves
 * it — so a second implementation in Python would be a copy that drifts, of
 * something the server has no use for.
 *
 * Three outcomes, and the third is the one that decides whether people trust the
 * feature:
 *   - `located`      the quote was found, here is its range;
 *   - `ambiguous`    found more than once and the context could not choose —
 *                    treated as orphaned rather than guessing;
 *   - `orphaned`     the text it was written against is gone.
 *
 * An orphan is never silently dropped and never re-anchored to the nearest
 * lookalike. It keeps the text it was written against so the comment stays
 * legible as history.
 */

export interface TextAnchor {
  quote: string;
  prefix?: string;
  suffix?: string;
}

export type AnchorLocation =
  | { status: "located"; start: number; end: number }
  | { status: "ambiguous" }
  | { status: "orphaned" };

/** How much context is captured either side of a selection. */
export const ANCHOR_CONTEXT_CHARS = 32;

/** Build an anchor from a selection within `text`. */
export function makeAnchor(text: string, start: number, end: number): TextAnchor {
  return {
    quote: text.slice(start, end),
    prefix: text.slice(Math.max(0, start - ANCHOR_CONTEXT_CHARS), start),
    suffix: text.slice(end, end + ANCHOR_CONTEXT_CHARS),
  };
}

/** Every index at which `needle` occurs in `haystack`. */
function occurrences(haystack: string, needle: string): number[] {
  const found: number[] = [];
  if (!needle) return found;
  let from = 0;
  for (;;) {
    const at = haystack.indexOf(needle, from);
    if (at === -1) return found;
    found.push(at);
    from = at + 1; // overlapping occurrences still count
  }
}

/** How many trailing chars of `a` match the leading chars of `b`. */
function commonSuffixLength(a: string, b: string): number {
  const max = Math.min(a.length, b.length);
  let n = 0;
  while (n < max && a[a.length - 1 - n] === b[b.length - 1 - n]) n++;
  return n;
}

function commonPrefixLength(a: string, b: string): number {
  const max = Math.min(a.length, b.length);
  let n = 0;
  while (n < max && a[n] === b[n]) n++;
  return n;
}

/**
 * Find where an anchor points in `text`.
 *
 * A unique quote resolves immediately. A repeated one is scored by how much of
 * the stored prefix and suffix still surrounds each candidate, and the best
 * scoring one wins — but only if it beats the runner-up. A tie is `ambiguous`,
 * not a coin flip: putting a comment on the wrong "see below" is worse than
 * admitting the anchor no longer resolves.
 */
export function locateAnchor(text: string, anchor: TextAnchor): AnchorLocation {
  const hits = occurrences(text, anchor.quote);
  if (hits.length === 0) return { status: "orphaned" };
  if (hits.length === 1) {
    return { status: "located", start: hits[0], end: hits[0] + anchor.quote.length };
  }

  const prefix = anchor.prefix ?? "";
  const suffix = anchor.suffix ?? "";
  const scored = hits.map((at) => ({
    at,
    score:
      commonSuffixLength(prefix, text.slice(Math.max(0, at - prefix.length), at)) +
      commonPrefixLength(suffix, text.slice(at + anchor.quote.length)),
  }));
  scored.sort((a, b) => b.score - a.score);
  if (scored.length > 1 && scored[0].score === scored[1].score) return { status: "ambiguous" };
  return {
    status: "located",
    start: scored[0].at,
    end: scored[0].at + anchor.quote.length,
  };
}

/** Convenience for the rail: located anchors first, in document order, then the
 *  ones that no longer resolve — which is where an orphan belongs, visible but
 *  out of the way. */
export function orderByAnchor<T extends { anchor?: TextAnchor | null }>(
  text: string,
  rows: T[],
): { row: T; location: AnchorLocation | null }[] {
  const withLocation = rows.map((row) => ({
    row,
    location: row.anchor ? locateAnchor(text, row.anchor) : null,
  }));
  return withLocation.sort((a, b) => {
    const aa = a.location?.status === "located" ? a.location.start : Number.MAX_SAFE_INTEGER;
    const bb = b.location?.status === "located" ? b.location.start : Number.MAX_SAFE_INTEGER;
    return aa - bb;
  });
}
