/**
 * Heading anchors and the outline behind `radd:toc` (RADD-710).
 *
 * Kept as plain functions over the markdown SOURCE rather than over the rendered
 * DOM: the table of contents renders in the same pass as the headings it points
 * at, so there is no rendered tree to read yet, and a source pass is testable
 * without a browser.
 */

export interface OutlineHeading {
  level: number;
  text: string;
  id: string;
}

/**
 * A heading's anchor id. Same shape as a page slug, and DERIVED FROM THE TEXT so
 * two independent renders (the heading itself and the contents block) agree
 * without sharing state. Duplicate headings get `-2`, `-3` in document order,
 * which is why both callers must walk the document the same way.
 */
export function headingAnchorId(text: string, seen?: Map<string, number>): string {
  const base =
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 80) || "section";
  if (!seen) return base;
  const count = (seen.get(base) ?? 0) + 1;
  seen.set(base, count);
  return count === 1 ? base : `${base}-${count}`;
}

/** Fenced-code boundaries, so a `#` inside a code block is not a heading. */
const FENCE = /^\s*(```|~~~)/;
const ATX = /^(#{1,6})\s+(.+?)\s*#*\s*$/;

/**
 * The document's headings, in order, to `maxDepth`. ATX (`## Title`) only —
 * Setext underlines are not something the editor emits, and accepting them
 * would mean tracking the previous line for every line in the document.
 */
export function headingsOf(markdown: string, maxDepth = 6): OutlineHeading[] {
  const seen = new Map<string, number>();
  const out: OutlineHeading[] = [];
  let inFence = false;
  for (const line of markdown.split("\n")) {
    if (FENCE.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const match = ATX.exec(line);
    if (!match) continue;
    const level = match[1].length;
    const text = match[2].trim();
    // The id is allocated for EVERY heading, so ids stay stable when a `depth`
    // cap hides one — otherwise capping the outline would renumber the anchors.
    const id = headingAnchorId(text, seen);
    if (level <= maxDepth) out.push({ level, text, id });
  }
  return out;
}
