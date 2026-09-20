import type { Node as ProseNode } from "@milkdown/kit/prose/model";
import { locateAnchor, type TextAnchor } from "../../lib/anchoring";

/**
 * Which inline comments an AI review would strand (RADD-1274).
 *
 * An inline comment is a text quote re-located on every render (RADD-726); a
 * passage the replacement removes turns its comment into an orphan. The rule
 * that an orphan is never resolved on anyone's behalf stands — this only
 * COUNTS them, so the review can say so and offer to resolve them in the same
 * click that removes the passages.
 *
 * Both documents are read the way the page rail reads the rendered body: text
 * runs joined with nothing between them (`lib/dom-text.ts::renderedText`), so
 * a quote that located there locates here.
 */
export interface InlineAnchorRef {
  id: string;
  anchor: TextAnchor;
}

const textOf = (doc: ProseNode): string => doc.textBetween(0, doc.content.size, "", "");

/** Ids of the anchors that locate in `before` and no longer locate in `after`. */
export function detachedComments(
  anchors: InlineAnchorRef[],
  before: ProseNode,
  after: ProseNode,
): string[] {
  if (anchors.length === 0) return [];
  const was = textOf(before);
  const now = textOf(after);
  return anchors
    .filter(
      ({ anchor }) =>
        locateAnchor(was, anchor).status === "located" &&
        locateAnchor(now, anchor).status !== "located",
    )
    .map(({ id }) => id);
}
