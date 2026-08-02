/**
 * The point of the diff fork: inline changes grouped per TEXTBLOCK, with
 * word-boundary visual expansion.
 *
 * The upstream decoration plugin renders one Accept/Reject pair per raw
 * changeset chunk — and the changeset tokenizes per CHARACTER, so an AI
 * rewrite of a paragraph yields a wall of buttons and mid-word fragments
 * ("~~D~~d emo"). Here every inline change is bucketed by its enclosing
 * textblock (the paragraph inside a list item, not the whole list), the
 * bucket reviews as ONE unit, and each visual run is expanded to word
 * boundaries by swallowing the unchanged characters shared by both docs
 * ("~~Demo~~ demo").
 *
 * Exact ranges vs visual runs: `range` is the union of the members' EXACT
 * changeset ranges — accept/reject must apply precisely those (the swallowed
 * word characters are identical on both sides, so replacing the union range
 * with the union B-slice is still exact). `runs` are word-expanded and purely
 * visual.
 */

import type { Node } from "@milkdown/kit/prose/model";

import type { DiffSpan, MergedChange } from "./merge-changes";

/** Leaf inline atoms (hard breaks…) count as ONE position inside a textblock;
 * mirroring them as one char keeps string offsets == doc positions. U+FFFC is
 * a non-space char, so word expansion crosses leaves like any word character. */
const LEAF_CHAR = "￼";

export interface InlineGroup {
  /** Exact union of the members' changeset ranges — what accept/reject applies. */
  range: DiffSpan;
  /** Word-expanded visual runs (strike + inserted-widget per run). */
  runs: DiffSpan[];
  /** Where the group's single controls pair anchors: end of the enclosing
   * textblock's content in the old doc. */
  controlsPos: number;
}

function isWordChar(ch: string | undefined): boolean {
  return ch !== undefined && !/\s/.test(ch);
}

interface BlockText {
  start: number; // content start of the textblock
  end: number; // content end
  text: string; // one char per position in [start, end)
}

/** The textblock content around `pos`, or null at depth 0 / non-textblock —
 * callers fall back to unexpanded rendering there. */
function blockTextAt(doc: Node, pos: number): BlockText | null {
  const $pos = doc.resolve(pos);
  if ($pos.depth === 0 || !$pos.parent.isTextblock) return null;
  const start = $pos.start($pos.depth);
  const end = $pos.end($pos.depth);
  return { start, end, text: doc.textBetween(start, end, undefined, LEAF_CHAR) };
}

/** Expand one change to word boundaries. A boundary only expands when it
 * SPLITS a word: the unchanged char just outside it is a word char AND the
 * change's edge char (on either doc's side) is one too. Expansion amounts are
 * measured once on the old doc's unchanged text and applied to both docs —
 * unchanged text is identical in both by construction. */
function expandToWordBoundaries(
  change: DiffSpan,
  blockA: BlockText,
  blockB: BlockText | null,
): DiffSpan {
  const charA = (pos: number): string | undefined =>
    pos >= blockA.start && pos < blockA.end ? blockA.text[pos - blockA.start] : undefined;
  const charB = (pos: number): string | undefined =>
    blockB && pos >= blockB.start && pos < blockB.end
      ? blockB.text[pos - blockB.start]
      : undefined;

  const afterChar = charA(change.toA);
  const beforeChar = charA(change.fromA - 1);
  const lastA = change.toA > change.fromA ? charA(change.toA - 1) : undefined;
  const firstA = change.toA > change.fromA ? charA(change.fromA) : undefined;
  const lastB = change.toB > change.fromB ? charB(change.toB - 1) : undefined;
  const firstB = change.toB > change.fromB ? charB(change.fromB) : undefined;

  let left = 0;
  if (isWordChar(beforeChar) && (isWordChar(firstA) || isWordChar(firstB))) {
    while (isWordChar(charA(change.fromA - left - 1))) left++;
  }
  let right = 0;
  if (isWordChar(afterChar) && (isWordChar(lastA) || isWordChar(lastB))) {
    while (isWordChar(charA(change.toA + right))) right++;
  }
  // The same unchanged chars flank the change in the new doc; clamp to its
  // block bounds all the same (defensive — they should always fit).
  if (blockB) {
    left = Math.min(left, change.fromB - blockB.start);
    right = Math.min(right, blockB.end - change.toB);
  }
  return {
    fromA: change.fromA - left,
    toA: change.toA + right,
    fromB: change.fromB - left,
    toB: change.toB + right,
  };
}

/** Merge sorted visual runs that overlap or touch on either axis. */
function mergeRuns(runs: DiffSpan[]): DiffSpan[] {
  const sorted = [...runs].sort((a, b) => a.fromA - b.fromA || a.fromB - b.fromB);
  const merged: DiffSpan[] = [];
  for (const run of sorted) {
    const prev = merged[merged.length - 1];
    if (prev && (run.fromA <= prev.toA || run.fromB <= prev.toB)) {
      prev.toA = Math.max(prev.toA, run.toA);
      prev.toB = Math.max(prev.toB, run.toB);
    } else {
      merged.push({ ...run });
    }
  }
  return merged;
}

/** Bucket inline changes by their enclosing textblock in the old doc; one
 * group (one controls pair) per touched block. */
export function groupInlineChanges(
  doc: Node,
  newDoc: Node,
  changes: MergedChange[],
): InlineGroup[] {
  interface Bucket {
    block: BlockText;
    members: MergedChange[];
  }
  const buckets = new Map<number, Bucket>();
  const loners: InlineGroup[] = [];

  for (const change of changes) {
    const block = blockTextAt(doc, change.fromA);
    if (!block) {
      // Defensive: an inline-classified change should always sit inside a
      // textblock — render it standalone and unexpanded if it somehow doesn't.
      loners.push({
        range: { ...change },
        runs: [{ ...change }],
        controlsPos: change.toA,
      });
      continue;
    }
    const bucket = buckets.get(block.start);
    if (bucket) bucket.members.push(change);
    else buckets.set(block.start, { block, members: [change] });
  }

  const groups: InlineGroup[] = [];
  for (const { block, members } of buckets.values()) {
    const range: DiffSpan = {
      fromA: Math.min(...members.map((m) => m.fromA)),
      toA: Math.max(...members.map((m) => m.toA)),
      fromB: Math.min(...members.map((m) => m.fromB)),
      toB: Math.max(...members.map((m) => m.toB)),
    };
    const runs = mergeRuns(
      members.map((member) =>
        expandToWordBoundaries(member, block, blockTextAt(newDoc, member.fromB)),
      ),
    );
    groups.push({ range, runs, controlsPos: block.end });
  }
  return [...groups, ...loners];
}
