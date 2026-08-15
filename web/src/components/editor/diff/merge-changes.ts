/*
 * Portions Copyright (c) Milkdown contributors (Mirone and others).
 * Ported/adapted from @milkdown/components (MIT). Full license text:
 * THIRD-PARTY-NOTICES.md at the repository root.
 * SPDX-License-Identifier: AGPL-3.0-only AND MIT
 */
/**
 * Custom-block merging + cross-boundary splitting for the diff decoration
 * fork — ported from `@milkdown/components/src/diff/merge-changes.ts` (not
 * exported by the package). Logic is unchanged. The per-BLOCK grouping that
 * motivates the fork lives in `word-groups.ts`, not here.
 */

import type { Node } from "@milkdown/kit/prose/model";

import {
  getCustomBlockAncestor,
  getCustomBlockAt,
  getTopLevelBlockRange,
  trailingEmptyParagraphStart,
} from "./doc-utils";

/** A change range in both docs (structurally matches prosemirror-changeset's
 * `Change` — only these four fields are ever read). */
export interface DiffSpan {
  fromA: number;
  toA: number;
  fromB: number;
  toB: number;
}

export interface MergedChange extends DiffSpan {
  /** Merged from a custom-block node (table, image-block, code_block). */
  isCustomBlock: boolean;
}

export interface ChangeSegment extends DiffSpan {
  isBlock: boolean;
}

/** Half-open interval overlap. */
function overlaps(a1: number, a2: number, b1: number, b2: number): boolean {
  return a1 < b2 && a2 > b1;
}

/** Does [from, to) touch a custom block? Empty ranges only count when the
 * anchor is INSIDE one (a point between blocks touches neither neighbour). */
function touchesCustomBlockRange(
  doc: Node,
  from: number,
  to: number,
  customBlockTypes: Set<string>,
): boolean {
  if (from === to) return getCustomBlockAncestor(doc, from, customBlockTypes) != null;
  return (
    getCustomBlockAt(doc, from, customBlockTypes) != null ||
    getCustomBlockAt(doc, to, customBlockTypes, true) != null
  );
}

/** Split a cross-boundary change into inline + block visual segments (null
 * when no split is needed, or when a split would nest block DOM in a span). */
export function splitCrossBoundaryChange(
  doc: Node,
  newDoc: Node,
  change: MergedChange,
): ChangeSegment[] | null {
  const $fromA = doc.resolve(change.fromA);
  // Only split when fromA sits in a TOP-LEVEL textblock; nested textblocks
  // (list-item paragraphs, blockquotes) would produce invalid DOM.
  if (!$fromA.parent.isTextblock || $fromA.depth < 1) return null;
  if (!$fromA.node(1).isTextblock) return null;

  const blockEndA = $fromA.after(1);

  // The matching split point in newDoc — only a real split when fromB is also
  // inside a top-level textblock, else the inline segment would hold block DOM.
  const $fromB = newDoc.resolve(change.fromB);
  let splitB: number;
  if ($fromB.depth >= 1 && $fromB.node(1).isTextblock) {
    splitB = $fromB.after(1);
    if (splitB > change.toB) splitB = change.toB;
  } else {
    splitB = change.fromB;
  }

  if (blockEndA >= change.toA && splitB >= change.toB) return null;

  const segments: ChangeSegment[] = [];
  if (blockEndA > change.fromA || splitB > change.fromB) {
    segments.push({
      fromA: change.fromA,
      toA: Math.min(blockEndA, change.toA),
      fromB: change.fromB,
      toB: splitB,
      isBlock: false,
    });
  }
  // Normalized so fromA <= toA when the deletion stays within the textblock
  // but the insertion continues into following blocks.
  if (change.toA > blockEndA || change.toB > splitB) {
    segments.push({
      fromA: blockEndA,
      toA: Math.max(blockEndA, change.toA),
      fromB: splitB,
      toB: change.toB,
      isBlock: true,
    });
  }
  return segments.length > 1 ? segments : null;
}

function changeTouchesCustomBlock(
  change: DiffSpan,
  doc: Node,
  newDoc: Node,
  customBlockTypes: Set<string>,
): boolean {
  return (
    touchesCustomBlockRange(doc, change.fromA, change.toA, customBlockTypes) ||
    touchesCustomBlockRange(newDoc, change.fromB, change.toB, customBlockTypes)
  );
}

/** Merge changes falling within custom-block nodes into single block-level
 * changes — custom node views can't render inline decorations. */
export function mergeBlockChanges(
  pending: readonly DiffSpan[],
  doc: Node,
  newDoc: Node,
  customBlockTypes: Set<string>,
): MergedChange[] {
  const result: MergedChange[] = [];
  const consumed = new Set<number>();

  for (let i = 0; i < pending.length; i++) {
    if (consumed.has(i)) continue;
    const change = pending[i]!;

    if (!changeTouchesCustomBlock(change, doc, newDoc, customBlockTypes)) {
      result.push({ ...change, isCustomBlock: false });
      continue;
    }

    // Expand each side to its enclosing top-level block where that side
    // actually touches a custom block; union with the original range so
    // nothing gets truncated.
    const blockRangeA = expandToCustomBlockRange(doc, change.fromA, change.toA, customBlockTypes);
    const blockRangeB = expandToCustomBlockRange(
      newDoc,
      change.fromB,
      change.toB,
      customBlockTypes,
    );
    const merged: MergedChange = {
      fromA: Math.min(blockRangeA?.from ?? change.fromA, change.fromA),
      toA: Math.max(blockRangeA?.to ?? change.toA, change.toA),
      fromB: Math.min(blockRangeB?.from ?? change.fromB, change.fromB),
      toB: Math.max(blockRangeB?.to ?? change.toB, change.toB),
      isCustomBlock: true,
    };
    consumed.add(i);

    // Absorb later changes overlapping the block range in either doc.
    for (let j = i + 1; j < pending.length; j++) {
      if (consumed.has(j)) continue;
      const other = pending[j]!;
      const overlapA =
        blockRangeA && overlaps(other.fromA, other.toA, blockRangeA.from, blockRangeA.to);
      const overlapB =
        blockRangeB && overlaps(other.fromB, other.toB, blockRangeB.from, blockRangeB.to);
      if (!overlapA && !overlapB) continue;
      consumed.add(j);
      merged.fromA = Math.min(merged.fromA, other.fromA);
      merged.toA = Math.max(merged.toA, other.toA);
      merged.fromB = Math.min(merged.fromB, other.fromB);
      merged.toB = Math.max(merged.toB, other.toB);
    }

    // Coalesce with every already-emitted custom-block change this one
    // overlaps — two seeds can independently expand over the same block.
    const absorbedIndexes: number[] = [];
    for (let k = 0; k < result.length; k++) {
      const prev = result[k]!;
      if (!prev.isCustomBlock) continue;
      const touchesA = overlaps(merged.fromA, merged.toA, prev.fromA, prev.toA);
      const touchesB = overlaps(merged.fromB, merged.toB, prev.fromB, prev.toB);
      if (!touchesA && !touchesB) continue;
      merged.fromA = Math.min(merged.fromA, prev.fromA);
      merged.toA = Math.max(merged.toA, prev.toA);
      merged.fromB = Math.min(merged.fromB, prev.fromB);
      merged.toB = Math.max(merged.toB, prev.toB);
      absorbedIndexes.push(k);
    }
    for (let k = absorbedIndexes.length - 1; k >= 0; k--) result.splice(absorbedIndexes[k]!, 1);
    result.push(merged);
  }

  return result;
}

/** Re-anchor pure inserts at the doc end BEFORE the trailing empty paragraph,
 * so the placeholder paragraph keeps its slot across recomputes. */
export function anchorTrailingInsertsBeforeEmptyParagraph(
  changes: MergedChange[],
  doc: Node,
): void {
  const trailingStart = trailingEmptyParagraphStart(doc);
  if (trailingStart === doc.content.size) return;
  for (const change of changes) {
    const isPureInsert = change.fromA === change.toA && change.fromB < change.toB;
    if (isPureInsert && change.fromA >= trailingStart) {
      change.fromA = trailingStart;
      change.toA = trailingStart;
    }
  }
}

/** The top-level block range enclosing a custom block touched by [from, to);
 * null when neither endpoint touches one. */
function expandToCustomBlockRange(
  doc: Node,
  from: number,
  to: number,
  customBlockTypes: Set<string>,
): { from: number; to: number } | null {
  if (from === to) {
    if (getCustomBlockAncestor(doc, from, customBlockTypes) == null) return null;
    return getTopLevelBlockRange(doc, from);
  }
  if (getCustomBlockAt(doc, from, customBlockTypes) != null) {
    return getTopLevelBlockRange(doc, from);
  }
  if (getCustomBlockAt(doc, to, customBlockTypes, true) != null) {
    return getTopLevelBlockRange(doc, to, true);
  }
  return null;
}
