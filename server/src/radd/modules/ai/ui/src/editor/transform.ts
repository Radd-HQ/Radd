import type { EditorTransform } from "@radd/plugin-sdk";
import { streamSse } from "../sse";
import { AiEndpoint, aiErrorText, isAiGone } from "../transport";
import { INSTRUCTION_ACTION_PREFIX, type AiRun } from "./gate";
import { droppedCount, maskProtected, restoreProtected } from "./protect";

/**
 * An AI run as an editor transform (RADD-1395).
 *
 * The editor owns the review; this owns what the replacement IS: the request to
 * `POST /ai/editor/stream` (a curated action by id, or the typed instruction) and the RADD-1274
 * guarantee — every `radd:*` fence, image and attachment link is masked behind `⟦keep-N⟧` before
 * the model sees the text and restored after, and one the model dropped is appended rather than
 * lost. The editor never learns there was a mask.
 */

/** Runs in flight, so withdrawing the plugin stops them (`abortAiRuns`). */
const inFlight = new Set<AbortController>();

/** Stop every AI run in flight — the plugin is being withdrawn. Each resolves as withdrawn. */
export function abortAiRuns(): void {
  for (const controller of inFlight) controller.abort();
  inFlight.clear();
}

const droppedNote = (count: number) =>
  count === 1
    ? "The result left out 1 protected block (media, image or widget); it was kept at the end of the text."
    : `The result left out ${count} protected blocks (media, images or widgets); they were kept at the end of the text.`;

export function aiTransform(run: AiRun): EditorTransform {
  return {
    label: run.label,
    emptyMessage: "The AI suggested no changes.",
    run: async (input, { signal, onText }) => {
      // The model reads placeholders where the media, images and extension blocks are, and never
      // a line of syntax it could drop. A selection is masked with the DOCUMENT's ids, so context
      // and target agree on what `⟦keep-3⟧` is; the blocks restored are the replaced part's.
      const document = maskProtected(input.document);
      const whole = input.selection === "";
      const selection = whole ? { masked: "", kept: [] } : maskProtected(input.selection, document.kept);
      const kept = whole ? document.kept : selection.kept;
      const body = run.instruction.startsWith(INSTRUCTION_ACTION_PREFIX)
        ? { action_id: run.instruction.slice(INSTRUCTION_ACTION_PREFIX.length), document: document.masked, selection: selection.masked }
        : { instruction: run.instruction, document: document.masked, selection: selection.masked };

      const controller = new AbortController();
      const stop = () => controller.abort();
      signal.addEventListener("abort", stop);
      inFlight.add(controller);
      let text = "";
      try {
        for await (const chunk of streamSse(AiEndpoint.editorStream, body, controller.signal)) {
          text += chunk;
          onText(restoreProtected(text, kept));
        }
      } catch (error) {
        // Stopped, or withdrawn with the plugin: not a failure.
        if (controller.signal.aborted) return null;
        throw new Error(isAiGone(error) ? "AI editor actions are unavailable." : aiErrorText(error));
      } finally {
        signal.removeEventListener("abort", stop);
        inFlight.delete(controller);
      }
      if (controller.signal.aborted) return null;
      if (!text.trim()) return { replacement: "" };
      // The reply with the media, images and extension blocks back in their places — and any it
      // dropped appended, never lost (RADD-1274).
      const dropped = droppedCount(text, kept);
      return { replacement: restoreProtected(text, kept), notes: dropped > 0 ? [droppedNote(dropped)] : [] };
    },
  };
}
