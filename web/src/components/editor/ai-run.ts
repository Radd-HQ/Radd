import { commandsCtx, editorViewCtx, parserCtx, serializerCtx } from "@milkdown/kit/core";
import type { Ctx } from "@milkdown/kit/ctx";
import {
  clearDiffReviewCmd,
  diffPluginKey,
  getPendingChanges,
  startDiffReviewFromDocCmd,
} from "@milkdown/kit/plugin/diff";
import { ApiPath } from "../../lib/constants";
import { streamSse } from "../../lib/sse";
import { INSTRUCTION_ACTION_PREFIX, type AiRun } from "./ai";
import { droppedCount, maskProtected, restoreProtected, type KeptBlock } from "./ai-protect";
import type { Node as ProseNode } from "@milkdown/kit/prose/model";

/**
 * Running an AI transform, ours (RADD-753).
 *
 * We already owned more of this than it looked: the curated action list comes
 * from our server, the streaming is our SSE endpoint, the diff review is our
 * fork, and the toolbar button was ours. What was borrowed was the ORCHESTRATION
 * — and it came with a workaround that was a symptom rather than a bug: the
 * command had to be dispatched BY NAME, because importing it from the subpath
 * entry bound a second, dead copy of the feature module.
 *
 * The orchestration turns out to be four steps, and none of them needs a third
 * party:
 *
 *   1. serialise the document and the selection to markdown;
 *   2. stream the replacement from `POST /ai/editor/stream`;
 *   3. splice it back over the selection to get the NEW DOC — as a document,
 *      not as markdown, so nothing round-trips through the parser twice;
 *   4. hand that doc to the diff plugin, which is what our decoration fork
 *      renders per-textblock accept/reject over.
 *
 * Step 3 is the one worth reading twice. `state.tr.replaceWith(...)` produces a
 * transaction whose `.doc` is the result WITHOUT dispatching it, so the new
 * document can be computed and diffed while the editor still shows the old one.
 */

/** What the endpoint is told about where the run applies. */
interface RunScope {
  /** The whole document, as markdown — with every protected block masked
   *  (RADD-1274): the model reads placeholders where the media, images and
   *  extension blocks are, and never a line of syntax it could drop. */
  document: string;
  /** The selected part, empty when the run is document-wide. Masked too, with
   *  the document's ids, so context and target agree on what `⟦keep-3⟧` is. */
  selection: string;
  /** The blocks masked out of the part the run REPLACES — what `restore`
   *  puts back into the reply. */
  kept: KeptBlock[];
  from: number;
  to: number;
}

/**
 * What the run applies to.
 *
 * `range` is passed in by chrome that CAPTURED it, not read from the live
 * selection — opening a prompt field moves focus out of the editor and
 * collapses the selection, which silently turned every selection-scoped run
 * into a document-wide one.
 */
export function scopeOf(ctx: Ctx, range?: { from: number; to: number }): RunScope {
  const view = ctx.get(editorViewCtx);
  const serializer = ctx.get(serializerCtx);
  const { state } = view;
  const from = range?.from ?? state.selection.from;
  const to = range?.to ?? state.selection.to;
  const empty = from >= to;
  const document = maskProtected(serializer(state.doc));
  // A selection is serialised by cutting the DOC, not by slicing text: a
  // range spanning two list items is markdown, not a substring.
  const selection = empty
    ? { masked: "", kept: [] }
    : maskProtected(serializer(state.doc.cut(from, to)), document.kept);
  return {
    document: document.masked,
    selection: selection.masked,
    kept: empty ? document.kept : selection.kept,
    from,
    to,
  };
}

/** A review is already open — a second run would diff against a pending diff. */
export const reviewPending = (ctx: Ctx): boolean =>
  diffPluginKey.getState(ctx.get(editorViewCtx).state) != null;

/**
 * How a run ended — the three outcomes the progress surface has to tell apart
 * (RADD-762). They used to be indistinguishable: `done` resolved `void` for
 * both "there is a review waiting" and "the model sent nothing", and REJECTED
 * for a cancel, so pressing Stop reported that the AI had failed.
 */
export const AiRunOutcome = {
  /** A diff review is open and waiting to be accepted or rejected. */
  review: "review",
  /** The run finished with nothing to change — no review was opened. */
  empty: "empty",
  /** Stopped by the person who started it. Not a failure. */
  aborted: "aborted",
} as const;

export type AiRunOutcomeValue = (typeof AiRunOutcome)[keyof typeof AiRunOutcome];

export interface AiRunHandle {
  /** Resolves with the outcome once the stream ends and any diff is handed
   *  over; rejects only on a real failure (never on cancel). */
  done: Promise<AiRunOutcomeValue>;
  /** Text so far, for the progress surface — protected blocks already restored. */
  onChunk: (listener: (text: string) => void) => void;
  cancel: () => void;
  /** The document the open review proposes (RADD-1274), for chrome that wants
   *  to say what accepting it would do — null until a review is open. */
  proposed: () => ProseNode | null;
  /** Protected blocks the model dropped, which `restore` appended at the end. */
  dropped: () => number;
}

/**
 * Stream a transform and land it as a reviewable diff.
 *
 * Applied at the END rather than streamed into the document — which is what
 * `diffReviewOnEnd` did, so this is the existing behaviour, made explicit.
 * Streaming into the doc and then diffing it against itself would be showing
 * someone a change and then asking them to approve it.
 */
export function runAi(
  ctx: Ctx,
  run: AiRun,
  range?: { from: number; to: number },
): AiRunHandle {
  const controller = new AbortController();
  const listeners: ((text: string) => void)[] = [];
  const scope = scopeOf(ctx, range);
  const body = run.instruction.startsWith(INSTRUCTION_ACTION_PREFIX)
    ? {
        action_id: run.instruction.slice(INSTRUCTION_ACTION_PREFIX.length),
        document: scope.document,
        selection: scope.selection,
      }
    : { instruction: run.instruction, document: scope.document, selection: scope.selection };

  let proposed: ProseNode | null = null;
  let dropped = 0;
  const done = (async (): Promise<AiRunOutcomeValue> => {
    let text = "";
    try {
      for await (const chunk of streamSse(ApiPath.aiEditorStream, body, controller.signal)) {
        text += chunk;
        const shown = restoreProtected(text, scope.kept);
        for (const listener of listeners) listener(shown);
      }
    } catch (error) {
      // Cancelling is the only way the fetch can reject with the signal already
      // flagged, and it is not a failure — reporting it as one is how Stop came
      // to raise "AI provider unavailable" at the person who pressed it.
      if (controller.signal.aborted) return AiRunOutcome.aborted;
      throw error;
    }
    if (controller.signal.aborted) return AiRunOutcome.aborted;
    if (!text.trim()) return AiRunOutcome.empty;
    // The model's reply with the media, images and extension blocks back in
    // their places — and any it dropped appended, never lost (RADD-1274).
    dropped = droppedCount(text, scope.kept);
    proposed = applyAsDiff(ctx, scope, restoreProtected(text, scope.kept));
    return proposed ? AiRunOutcome.review : AiRunOutcome.empty;
  })();

  return {
    done,
    onChunk: (listener) => listeners.push(listener),
    cancel: () => controller.abort(),
    proposed: () => proposed,
    dropped: () => dropped,
  };
}

/** Splice the result over the selection and open the review. Returns the
 *  proposed document, or null when the reply parsed to nothing or changed
 *  nothing, so the caller can say so rather than go quiet. */
function applyAsDiff(ctx: Ctx, scope: RunScope, replacement: string): ProseNode | null {
  const view = ctx.get(editorViewCtx);
  const parser = ctx.get(parserCtx);
  const parsed = parser(replacement);
  if (!parsed) return null;
  const { state } = view;
  const newDoc =
    scope.selection === ""
      ? parsed
      : // A transaction that is never dispatched: `.doc` is the result, which is
        // all the diff needs. The editor keeps showing the original until the
        // reviewer accepts something.
        state.tr.replaceWith(scope.from, scope.to, parsed.content).doc;
  const commands = ctx.get(commandsCtx);
  commands.call(startDiffReviewFromDocCmd.key, newDoc);
  const opened = diffPluginKey.getState(view.state);
  if (opened && getPendingChanges(opened).length > 0) return newDoc;
  // A rewrite that changed nothing still opens an ACTIVE review — `start` is the
  // one action the plugin's reducer does not run its "no pending changes" check
  // over. An active review blocks every document transaction (its
  // `filterTransaction`), so leaving one standing would answer "the AI changed
  // nothing" by making the editor read-only until a reload.
  if (opened) commands.call(clearDiffReviewCmd.key);
  return null;
}
