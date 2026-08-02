/**
 * Document helpers for the diff decoration fork — ported from
 * `@milkdown/components/src/diff/doc-utils.ts` (the package doesn't export
 * them). Logic is unchanged; only the imports and the class-prefix source
 * differ. See `decoration-plugin.ts` for why the fork exists.
 */

import type { Node } from "@milkdown/kit/prose/model";
import { Decoration } from "@milkdown/kit/prose/view";
import { DIFF_CLASS_PREFIX } from "@milkdown/kit/component/diff";

/** Does a range in a doc cross a top-level block boundary? */
export function isBlockSpanning(doc: Node, from: number, to: number): boolean {
  if (from === to) return false;
  const $from = doc.resolve(from);
  const $to = doc.resolve(to);
  // For depth-0 positions (between top-level nodes), index(0) gives the child
  // starting at/after the position — an exclusive range END means the previous
  // child was the one touched.
  const fromIndex = $from.index(0);
  const toIndex = $to.depth === 0 ? Math.max(0, $to.index(0) - 1) : $to.index(0);
  return fromIndex !== toIndex;
}

/** Does a range fully enclose any block node? (Partial overlaps don't count —
 * those are `isBlockSpanning`'s job.) */
export function hasBlockContent(doc: Node, from: number, to: number): boolean {
  if (from >= to) return false;
  const $from = doc.resolve(from);
  const $to = doc.resolve(to);
  if ($from.sameParent($to) && $from.parent.isTextblock) return false;
  let found = false;
  doc.nodesBetween(from, to, (node, pos) => {
    if (found) return false;
    if (!node.isBlock) return true;
    if (pos >= from && pos + node.nodeSize <= to) {
      found = true;
      return false;
    }
    return true;
  });
  return found;
}

/** Is [from, to) only the doc's trailing run of empty paragraphs? (Crepe keeps
 * an empty paragraph at the end — deleting it isn't a real change.) */
export function coversOnlyTrailingEmptyParagraphs(
  doc: Node,
  from: number,
  to: number,
): boolean {
  if (to !== doc.content.size) return false;
  const $from = doc.resolve(from);
  if ($from.depth !== 0) return false;
  for (let i = $from.index(0); i < doc.childCount; i++) {
    const child = doc.child(i);
    if (child.type.name !== "paragraph" || child.content.size > 0) return false;
  }
  return true;
}

/** Where the doc's trailing run of empty paragraphs begins (content size when
 * there is none). Inserts that target the doc end anchor here so the trailing
 * empty paragraph keeps its slot. */
export function trailingEmptyParagraphStart(doc: Node): number {
  let start = doc.content.size;
  for (let i = doc.childCount - 1; i >= 0; i--) {
    const child = doc.child(i);
    if (child.type.name !== "paragraph" || child.content.size > 0) break;
    start -= child.nodeSize;
  }
  return start;
}

/** For block-level widgets: a position BETWEEN blocks, never inside a
 * textblock's inline content. */
export function snapToBlockBoundary(doc: Node, pos: number): number {
  const $pos = doc.resolve(pos);
  for (let d = $pos.depth; d >= 1; d--) {
    if ($pos.node(d).isTextblock) return $pos.before(d);
  }
  return pos;
}

/** Iterate top-level nodes overlapping [from, to). */
export function forEachTopLevelNodeInRange(
  doc: Node,
  from: number,
  to: number,
  callback: (node: Node, start: number, end: number) => void,
): void {
  let pos = 0;
  for (let i = 0; i < doc.childCount; i++) {
    const child = doc.child(i);
    const nodeEnd = pos + child.nodeSize;
    if (pos >= to) break;
    if (nodeEnd > from && pos < to) callback(child, pos, nodeEnd);
    pos = nodeEnd;
  }
}

/** Node-level deletion decorations per top-level block — `Decoration.node`
 * reaches custom node views (CodeMirror, image-block) where inline can't. */
export function addBlockDeletionDecorations(
  doc: Node,
  from: number,
  to: number,
  decorations: Decoration[],
): void {
  forEachTopLevelNodeInRange(doc, from, to, (node, start, end) => {
    // Skip the trailing empty-paragraph placeholder.
    if (end === doc.content.size && node.type.name === "paragraph" && node.content.size === 0)
      return;
    decorations.push(
      Decoration.node(start, end, { class: `${DIFF_CLASS_PREFIX}-removed-block` }),
    );
  });
}

/** The enclosing top-level block range for a position. `endBoundary` picks the
 * node BEFORE a depth-0 position (for exclusive range ends). */
export function getTopLevelBlockRange(
  doc: Node,
  pos: number,
  endBoundary = false,
): { from: number; to: number } | null {
  if (pos < 0 || pos > doc.content.size) return null;
  const $pos = doc.resolve(Math.min(pos, doc.content.size));
  if ($pos.depth >= 1) return { from: $pos.before(1), to: $pos.after(1) };
  if (endBoundary) {
    const nodeBefore = $pos.nodeBefore;
    if (nodeBefore) return { from: pos - nodeBefore.nodeSize, to: pos };
    const nodeAfter = $pos.nodeAfter;
    if (nodeAfter) return { from: pos, to: pos + nodeAfter.nodeSize };
  } else {
    const nodeAfter = $pos.nodeAfter;
    if (nodeAfter) return { from: pos, to: pos + nodeAfter.nodeSize };
    const nodeBefore = $pos.nodeBefore;
    if (nodeBefore) return { from: pos - nodeBefore.nodeSize, to: pos };
  }
  return null;
}

/** Custom-block name in the ancestor chain of `pos` only — boundary positions
 * between blocks return null (a point anchor isn't "touching" its neighbours). */
export function getCustomBlockAncestor(
  doc: Node,
  pos: number,
  customBlockTypes: Set<string>,
): string | null {
  if (pos < 0 || pos > doc.content.size) return null;
  const $pos = doc.resolve(Math.min(pos, doc.content.size));
  for (let d = $pos.depth; d >= 0; d--) {
    const name = $pos.node(d).type.name;
    if (customBlockTypes.has(name)) return name;
  }
  return null;
}

/** Custom-block name at `pos`, including the sibling on the touched side —
 * nodeAfter for starts/points, nodeBefore when `endBoundary` (exclusive ends). */
export function getCustomBlockAt(
  doc: Node,
  pos: number,
  customBlockTypes: Set<string>,
  endBoundary = false,
): string | null {
  const ancestor = getCustomBlockAncestor(doc, pos, customBlockTypes);
  if (ancestor) return ancestor;
  const $pos = doc.resolve(Math.min(Math.max(pos, 0), doc.content.size));
  const sibling = endBoundary ? $pos.nodeBefore : $pos.nodeAfter;
  if (sibling && customBlockTypes.has(sibling.type.name)) return sibling.type.name;
  return null;
}

/** Complete top-level nodes within [from, to); [] unless the range aligns
 * exactly with node boundaries. */
export function collectTopLevelNodes(doc: Node, from: number, to: number): Node[] {
  const nodes: Node[] = [];
  let firstStart = -1;
  let lastEnd = -1;
  forEachTopLevelNodeInRange(doc, from, to, (node, start, end) => {
    if (firstStart === -1) firstStart = start;
    lastEnd = end;
    nodes.push(node);
  });
  if (nodes.length === 0 || firstStart !== from || lastEnd !== to) return [];
  return nodes;
}
