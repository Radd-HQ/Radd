/*
 * Portions Copyright (c) Milkdown contributors (Mirone and others).
 * Ported/adapted from @milkdown/components (MIT). Full license text:
 * THIRD-PARTY-NOTICES.md at the repository root.
 * SPDX-License-Identifier: AGPL-3.0-only AND MIT
 */
/**
 * Per-block AI diff review — a fork of Crepe's diff decoration plugin
 * (`@milkdown/components/src/diff/diff-decoration-plugin.ts`), swapped in by
 * RichEditor via `editor.remove(diffDecorationPlugin).use(raddDiffDecoration)`.
 *
 * Why a fork: upstream renders one Accept/Reject pair per raw changeset chunk
 * (character-granular — see `word-groups.ts`), which turns an AI rewrite into
 * a wall of buttons with mid-word fragments. Here inline changes group per
 * textblock: word-expanded strike/insert runs, ONE controls pair at the end of
 * each changed block. Block-level and custom-block changes keep upstream's
 * rendering (they were already one pair per change).
 *
 * It reuses upstream's ctx slices and CSS contract: `diffComponentConfig`
 * still carries labels + customBlockTypes (Crepe's AI feature keeps populating
 * it), and all decorations emit `milkdown-diff-*` classes so Crepe's theme
 * diff.css styles them untouched.
 *
 * One deliberate behavior fix: upstream's reject bookkeeping tests
 * `change.fromB < r.toB && change.toB > r.fromB`, which can NEVER match a
 * pure deletion (fromB === toB) — its Reject button is a silent no-op. Every
 * reject here dispatches the range padded by one position on each side; the
 * padding only reaches into the ≥1-token unchanged gap that always separates
 * changes, so it can't capture a neighbour.
 */

import type { CommandManager } from "@milkdown/kit/core";
import { commandsCtx } from "@milkdown/kit/core";
import type { Ctx } from "@milkdown/kit/ctx";
import type { DiffState } from "@milkdown/kit/plugin/diff";
import {
  acceptDiffRangeCmd,
  diffPluginKey,
  getPendingChanges,
  rejectDiffRangeCmd,
} from "@milkdown/kit/plugin/diff";
import { DIFF_CLASS_PREFIX, diffComponentConfig } from "@milkdown/kit/component/diff";
import type { Node } from "@milkdown/kit/prose/model";
import { DOMSerializer } from "@milkdown/kit/prose/model";
import { Plugin, PluginKey } from "@milkdown/kit/prose/state";
import type { EditorState } from "@milkdown/kit/prose/state";
import { Decoration, DecorationSet } from "@milkdown/kit/prose/view";
import { $prose } from "@milkdown/kit/utils";

import type { ChangeSegment, DiffSpan, MergedChange } from "./merge-changes";
import {
  anchorTrailingInsertsBeforeEmptyParagraph,
  mergeBlockChanges,
  splitCrossBoundaryChange,
} from "./merge-changes";
import {
  addBlockDeletionDecorations,
  collectTopLevelNodes,
  coversOnlyTrailingEmptyParagraphs,
  hasBlockContent,
  isBlockSpanning,
  snapToBlockBoundary,
} from "./doc-utils";
import { groupInlineChanges } from "./word-groups";

export const raddDiffDecorationKey = new PluginKey<DecorationSet>("RADD_DIFF_DECORATION");

/**
 * Marks a decoration as one of the Accept/Reject pairs (RADD-762).
 *
 * The run panel counts REVIEW UNITS — what a person has to click through — and
 * that is not the pending-change count: the whole point of this fork is that it
 * merges a changeset's chunks into one pair per changed block. Counting the
 * decorations we actually emit is the only number that matches the screen, and
 * a flag on the spec says so out loud where a `key.startsWith("controls-")`
 * test would be a naming coincidence waiting to break.
 */
export const DIFF_CONTROLS_SPEC = "raddDiffControls";

/** The rendered pairs, for chrome that scrolls between them. */
export const DIFF_CONTROLS_SELECTOR = `.${DIFF_CLASS_PREFIX}-controls`;

/** How many Accept/Reject pairs a state is currently rendering. */
export function countReviewUnits(decorations: DecorationSet): number {
  return decorations.find(
    undefined,
    undefined,
    (spec: Record<string, unknown>) => spec[DIFF_CONTROLS_SPEC] === true,
  ).length;
}

export const raddDiffDecoration = $prose((ctx) => {
  return new Plugin<DecorationSet>({
    key: raddDiffDecorationKey,
    state: {
      init: () => DecorationSet.empty,
      apply(tr, decorations, _oldState, newState) {
        const diffState = diffPluginKey.getState(newState);
        if (!diffState?.active) return DecorationSet.empty;
        // Rebuild on diff actions / doc changes; map through everything else.
        if (tr.getMeta(diffPluginKey) || tr.docChanged)
          return buildDecorations(ctx, newState.doc, diffState);
        return decorations.map(tr.mapping, tr.doc);
      },
    },
    props: {
      decorations(state: EditorState) {
        return raddDiffDecorationKey.getState(state) ?? DecorationSet.empty;
      },
    },
  });
});

/** See the module doc: rejects go out padded so pure deletions actually die. */
function dispatchDiff(commands: CommandManager, action: "accept" | "reject", range: DiffSpan) {
  if (action === "accept") {
    commands.call(acceptDiffRangeCmd.key, range);
  } else {
    commands.call(rejectDiffRangeCmd.key, {
      ...range,
      fromB: Math.max(0, range.fromB - 1),
      toB: range.toB + 1,
    });
  }
}

function buildDecorations(ctx: Ctx, doc: Node, diffState: DiffState): DecorationSet {
  const config = ctx.get(diffComponentConfig.key);
  const decorations: Decoration[] = [];
  const commands = ctx.get(commandsCtx);
  const customBlockTypes = new Set(config.customBlockTypes);

  const merged = mergeBlockChanges(getPendingChanges(diffState), doc, diffState.newDoc, customBlockTypes);
  anchorTrailingInsertsBeforeEmptyParagraph(merged, doc);

  const inline: MergedChange[] = [];

  for (let i = 0; i < merged.length; i++) {
    const change = merged[i]!;
    const isDeletion = change.fromA < change.toA;
    const isInsertion = change.fromB < change.toB;

    // The trailing empty paragraph is an editor placeholder, not a change.
    if (
      isDeletion &&
      !isInsertion &&
      coversOnlyTrailingEmptyParagraphs(doc, change.fromA, change.toA)
    )
      continue;

    const deletionSpansBlocks = isDeletion && isBlockSpanning(doc, change.fromA, change.toA);
    const deletionHasBlocks = isDeletion && hasBlockContent(doc, change.fromA, change.toA);
    const insertionHasBlocks =
      isInsertion && hasBlockContent(diffState.newDoc, change.fromB, change.toB);
    // Old-doc slices inside ONE top-level block (list-item text, blockquote
    // text) render inline even when they cross sub-block nodes.
    const deletionWithinSingleBlock =
      isDeletion &&
      !deletionSpansBlocks &&
      !deletionHasBlocks &&
      !change.isCustomBlock &&
      !insertionHasBlocks;
    const isBlockLevel =
      (deletionSpansBlocks || deletionHasBlocks || insertionHasBlocks) &&
      !deletionWithinSingleBlock;

    if (!isBlockLevel && !change.isCustomBlock) {
      inline.push(change);
      continue;
    }

    // Cross-boundary changes split into inline + block segments so both the
    // text edit and the block additions stay visible.
    if (isBlockLevel && !change.isCustomBlock) {
      const segments = splitCrossBoundaryChange(doc, diffState.newDoc, change);
      if (segments) {
        addCrossBoundaryDecorations(doc, diffState.newDoc, segments, change, i, commands, config, decorations);
        continue;
      }
    }

    // Whole-block change: block deletion overlays + block insert widget + one
    // controls pair (upstream's rendering, unchanged).
    if (isDeletion) {
      addBlockDeletionDecorations(doc, change.fromA, change.toA, decorations);
    }
    const widgetPos = snapToBlockBoundary(doc, isDeletion ? change.toA : change.fromA);
    if (isInsertion) {
      decorations.push(
        Decoration.widget(widgetPos, () => createInsertedWidget(diffState.newDoc, change, true), {
          side: -1,
          key: `added-${i}`,
        }),
      );
    }
    decorations.push(
      Decoration.widget(
        widgetPos,
        () => createControlsWidget(commands, true, change, config),
        { side: -1, key: `controls-${i}`, [DIFF_CONTROLS_SPEC]: true },
      ),
    );
  }

  // The fork's point: inline changes review per BLOCK, not per chunk — and
  // UNIFIED-DIFF style: the block's OLD text stacks above as a red-tinted
  // line (deleted words emphasized), the block itself reads as the NEW text
  // (green tint; deletions hidden, insertions emphasized). Interleaving both
  // texts word-by-word was unreadable the moment a rewrite touched more than
  // a few words.
  const groups = groupInlineChanges(doc, diffState.newDoc, inline);
  for (let g = 0; g < groups.length; g++) {
    const group = groups[g]!;
    const $from = doc.resolve(group.range.fromA);
    const inTextblock = $from.depth > 0 && $from.parent.isTextblock;
    const hasDeletion = group.runs.some((run) => run.fromA < run.toA);

    if (inTextblock) {
      const blockBefore = $from.before($from.depth);
      const blockAfter = $from.after($from.depth);
      if (hasDeletion) {
        const block = { start: $from.start($from.depth), end: $from.end($from.depth) };
        decorations.push(
          Decoration.widget(
            blockBefore,
            () => createOldBlockWidget(doc, block, group.runs),
            { side: -1, key: `group-old-${g}` },
          ),
        );
      }
      decorations.push(
        Decoration.node(blockBefore, blockAfter, { class: "radd-diff-new-block" }),
      );
    }

    for (let r = 0; r < group.runs.length; r++) {
      const run = group.runs[r]!;
      const runDeletes = run.fromA < run.toA;
      if (runDeletes) {
        decorations.push(
          Decoration.inline(run.fromA, run.toA, {
            // Inside a textblock the old text lives in the stacked widget —
            // hide it here so the block reads as the result. The defensive
            // non-textblock path keeps the strikethrough rendering.
            class: inTextblock ? "radd-diff-hidden" : `${DIFF_CLASS_PREFIX}-removed`,
          }),
        );
      }
      if (run.fromB < run.toB) {
        decorations.push(
          Decoration.widget(
            runDeletes ? run.toA : run.fromA,
            () => createInsertedWidget(diffState.newDoc, run, false),
            { side: -1, key: `group-added-${g}-${r}` },
          ),
        );
      }
    }
    decorations.push(
      Decoration.widget(
        group.controlsPos,
        () => createControlsWidget(commands, false, group.range, config),
        { side: 1, key: `group-controls-${g}`, [DIFF_CONTROLS_SPEC]: true },
      ),
    );
  }

  return DecorationSet.create(doc, decorations);
}

/** The unified diff's "− line": the enclosing block's ORIGINAL content with
 * the deleted runs emphasized. Serialized slice-by-slice so inline marks
 * (bold, code) survive. */
function createOldBlockWidget(
  doc: Node,
  block: { start: number; end: number },
  runs: DiffSpan[],
): HTMLElement {
  const dom = document.createElement("div");
  dom.className = "radd-diff-old-block";
  dom.contentEditable = "false";
  const serializer = DOMSerializer.fromSchema(doc.type.schema);
  const push = (from: number, to: number, removed: boolean) => {
    if (to <= from) return;
    const holder = document.createElement("span");
    if (removed) holder.className = "radd-diff-old-hl";
    holder.appendChild(serializer.serializeFragment(doc.slice(from, to).content));
    dom.appendChild(holder);
  };
  let pos = block.start;
  for (const run of runs) {
    if (run.fromA >= run.toA) continue; // pure insertion — nothing was removed
    push(pos, run.fromA, false);
    push(Math.max(pos, run.fromA), run.toA, true);
    pos = Math.max(pos, run.toA);
  }
  push(pos, block.end, false);
  return dom;
}

function addCrossBoundaryDecorations(
  doc: Node,
  newDoc: Node,
  segments: ChangeSegment[],
  change: MergedChange,
  changeIndex: number,
  commands: CommandManager,
  config: { acceptLabel: string; rejectLabel: string },
  decorations: Decoration[],
): void {
  for (let j = 0; j < segments.length; j++) {
    const seg = segments[j]!;
    const segDeletion = seg.fromA < seg.toA;
    const segInsertion = seg.fromB < seg.toB;
    if (segDeletion) {
      if (seg.isBlock) {
        addBlockDeletionDecorations(doc, seg.fromA, seg.toA, decorations);
      } else {
        decorations.push(
          Decoration.inline(seg.fromA, seg.toA, { class: `${DIFF_CLASS_PREFIX}-removed` }),
        );
      }
    }
    if (segInsertion) {
      const widgetPos = seg.isBlock
        ? snapToBlockBoundary(doc, segDeletion ? seg.toA : seg.fromA)
        : segDeletion
          ? seg.toA
          : seg.fromA;
      decorations.push(
        Decoration.widget(widgetPos, () => createInsertedWidget(newDoc, seg, seg.isBlock), {
          side: -1,
          key: `added-${changeIndex}-${j}`,
        }),
      );
    }
  }
  // One controls pair for the whole change, at a block boundary.
  const lastSeg = segments[segments.length - 1]!;
  const lastSegEnd = lastSeg.isBlock
    ? lastSeg.fromA < lastSeg.toA
      ? lastSeg.toA
      : lastSeg.fromA
    : change.toA;
  decorations.push(
    Decoration.widget(
      snapToBlockBoundary(doc, lastSegEnd),
      () => createControlsWidget(commands, true, change, config),
      { side: -1, key: `controls-${changeIndex}`, [DIFF_CONTROLS_SPEC]: true },
    ),
  );
}

function createInsertedWidget(
  newDoc: Node,
  range: { fromB: number; toB: number },
  isBlockLevel: boolean,
): HTMLElement {
  const dom = document.createElement(isBlockLevel ? "div" : "span");
  dom.className = `${DIFF_CLASS_PREFIX}-added`;
  dom.contentEditable = "false";
  if (isBlockLevel) dom.classList.add(`${DIFF_CLASS_PREFIX}-added-block`);

  const serializer = DOMSerializer.fromSchema(newDoc.type.schema);

  // Whole top-level nodes serialize node-by-node so complex nodes (tables)
  // keep their proper HTML structure.
  if (isBlockLevel) {
    const nodes = collectTopLevelNodes(newDoc, range.fromB, range.toB);
    if (nodes.length > 0) {
      const fragment = document.createDocumentFragment();
      for (const node of nodes) fragment.appendChild(serializer.serializeNode(node));
      dom.appendChild(fragment);
      return dom;
    }
  }

  const slice = newDoc.slice(range.fromB, range.toB);
  dom.appendChild(serializer.serializeFragment(slice.content));
  if (!dom.textContent?.trim() && !dom.querySelector("img, video, audio, canvas, svg")) {
    const fallback = newDoc.textBetween(range.fromB, range.toB, "\n", "\n");
    if (fallback.trim()) dom.textContent = fallback;
  }
  return dom;
}

function createControlsWidget(
  commands: CommandManager,
  isBlockLevel: boolean,
  range: DiffSpan,
  config: { acceptLabel: string; rejectLabel: string },
): HTMLElement {
  const dom = document.createElement(isBlockLevel ? "div" : "span");
  dom.className = `${DIFF_CLASS_PREFIX}-controls`;
  dom.contentEditable = "false";
  if (isBlockLevel) dom.classList.add(`${DIFF_CLASS_PREFIX}-controls-block`);

  const handler = (action: "accept" | "reject") => (event: Event) => {
    event.preventDefault();
    event.stopPropagation();
    dispatchDiff(commands, action, {
      fromA: range.fromA,
      toA: range.toA,
      fromB: range.fromB,
      toB: range.toB,
    });
  };

  const acceptBtn = document.createElement("button");
  acceptBtn.className = `${DIFF_CLASS_PREFIX}-accept`;
  acceptBtn.textContent = config.acceptLabel;
  acceptBtn.addEventListener("click", handler("accept"));

  const rejectBtn = document.createElement("button");
  rejectBtn.className = `${DIFF_CLASS_PREFIX}-reject`;
  rejectBtn.textContent = config.rejectLabel;
  rejectBtn.addEventListener("click", handler("reject"));

  dom.appendChild(acceptBtn);
  dom.appendChild(rejectBtn);
  return dom;
}
