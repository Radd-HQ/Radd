import { commandsCtx, editorViewCtx, parserCtx, serializerCtx } from "@milkdown/kit/core";
import type { Ctx } from "@milkdown/kit/ctx";
import {
  clearDiffReviewCmd,
  diffPluginKey,
  getPendingChanges,
  startDiffReviewFromDocCmd,
} from "@milkdown/kit/plugin/diff";
import type { Node as ProseNode } from "@milkdown/kit/prose/model";
import type { EditorRange, EditorTransform } from "@radd/plugin-sdk";

/**
 * Running a transform — a contribution's streamed replacement — as a reviewable diff
 * (RADD-753, generalised in RADD-1395).
 *
 * The editor owns four steps and the contribution one:
 *
 *   1. serialise the document and the selection to markdown;
 *   2. the CONTRIBUTION produces the replacement (`EditorTransform.run`) — its protocol, its
 *      prompt, and whatever it must protect through the round trip are its business;
 *   3. splice the replacement over the selection to get the NEW DOC — as a document, not as
 *      markdown, so nothing round-trips through the parser twice;
 *   4. hand that doc to the diff plugin, which our decoration fork renders per-textblock
 *      accept/reject over.
 *
 * Step 3 is the one worth reading twice. `state.tr.replaceWith(...)` produces a transaction whose
 * `.doc` is the result WITHOUT dispatching it, so the new document can be computed and diffed
 * while the editor still shows the old one.
 */

/** Where the run applies, and what it reads. */
interface RunScope {
  document: string;
  /** The selected part, empty when the run is document-wide. */
  selection: string;
  from: number;
  to: number;
}

/**
 * What the run applies to.
 *
 * `range` is passed in by chrome that CAPTURED it, not read from the live selection — opening a
 * prompt field moves focus out of the editor and collapses the selection, which silently turned
 * every selection-scoped run into a document-wide one.
 */
function scopeOf(ctx: Ctx, range?: EditorRange): RunScope {
  const view = ctx.get(editorViewCtx);
  const serializer = ctx.get(serializerCtx);
  const { state } = view;
  const from = range?.from ?? state.selection.from;
  const to = range?.to ?? state.selection.to;
  // A selection is serialised by cutting the DOC, not by slicing text: a range spanning two list
  // items is markdown, not a substring.
  const selection = from >= to ? "" : serializer(state.doc.cut(from, to));
  return { document: serializer(state.doc), selection, from, to };
}

/** A review is already open — a second run would diff against a pending diff. */
export const reviewPending = (ctx: Ctx): boolean =>
  diffPluginKey.getState(ctx.get(editorViewCtx).state) != null;

/** How a run ended; a cancel is `aborted`, never a failure. */
export const TransformOutcome = {
  /** A diff review is open and waiting to be accepted or rejected. */
  review: "review",
  /** The run finished with nothing to change — no review was opened. */
  empty: "empty",
  /** Stopped by the person who started it, or withdrawn by its contributor. Not a failure. */
  aborted: "aborted",
} as const;

type TransformOutcomeValue = (typeof TransformOutcome)[keyof typeof TransformOutcome];

interface TransformHandle {
  /** Resolves with the outcome once the run ends and any diff is handed over; rejects only on a
   *  real failure (never on cancel). */
  done: Promise<TransformOutcomeValue>;
  /** The replacement so far, for the progress surface. */
  onText: (listener: (text: string) => void) => void;
  cancel: () => void;
  /** The document the open review proposes (RADD-1274), for chrome that wants to say what
   *  accepting it would do — null until a review is open. */
  proposed: () => ProseNode | null;
  /** What the transform said about its result, shown beside the review. */
  notes: () => string[];
}

/**
 * Run a transform and land it as a reviewable diff.
 *
 * Applied at the END rather than streamed into the document. Streaming into the doc and then
 * diffing it against itself would be showing someone a change and then asking them to approve it.
 */
export function runTransform(ctx: Ctx, transform: EditorTransform, range?: EditorRange): TransformHandle {
  const controller = new AbortController();
  const listeners: ((text: string) => void)[] = [];
  const scope = scopeOf(ctx, range);
  let proposed: ProseNode | null = null;
  let notes: string[] = [];

  const done = (async (): Promise<TransformOutcomeValue> => {
    let result;
    try {
      result = await transform.run(
        { document: scope.document, selection: scope.selection },
        {
          signal: controller.signal,
          onText: (text) => {
            if (controller.signal.aborted) return;
            for (const listener of listeners) listener(text);
          },
        },
      );
    } catch (error) {
      // Cancelling is not a failure — reporting it as one is how Stop came to raise an error at
      // the person who pressed it.
      if (controller.signal.aborted) return TransformOutcome.aborted;
      throw error;
    }
    if (controller.signal.aborted || result === null) return TransformOutcome.aborted;
    if (!result.replacement.trim()) return TransformOutcome.empty;
    notes = result.notes ?? [];
    proposed = applyAsDiff(ctx, scope, result.replacement);
    return proposed ? TransformOutcome.review : TransformOutcome.empty;
  })();

  return {
    done,
    onText: (listener) => listeners.push(listener),
    cancel: () => controller.abort(),
    proposed: () => proposed,
    notes: () => notes,
  };
}

/** Splice the result over the selection and open the review. Returns the proposed document, or
 *  null when the reply parsed to nothing or changed nothing, so the caller can say so rather than
 *  go quiet. */
function applyAsDiff(ctx: Ctx, scope: RunScope, replacement: string): ProseNode | null {
  const view = ctx.get(editorViewCtx);
  const parser = ctx.get(parserCtx);
  const parsed = parser(replacement);
  if (!parsed) return null;
  const { state } = view;
  const newDoc =
    scope.selection === ""
      ? parsed
      : // A transaction that is never dispatched: `.doc` is the result, which is all the diff
        // needs. The editor keeps showing the original until the reviewer accepts something.
        state.tr.replaceWith(scope.from, scope.to, parsed.content).doc;
  const commands = ctx.get(commandsCtx);
  commands.call(startDiffReviewFromDocCmd.key, newDoc);
  const opened = diffPluginKey.getState(view.state);
  if (opened && getPendingChanges(opened).length > 0) return newDoc;
  // A rewrite that changed nothing still opens an ACTIVE review — `start` is the one action the
  // plugin's reducer does not run its "no pending changes" check over. An active review blocks
  // every document transaction (its `filterTransaction`), so leaving one standing would answer
  // "nothing changed" by making the editor read-only until a reload.
  if (opened) commands.call(clearDiffReviewCmd.key);
  return null;
}
