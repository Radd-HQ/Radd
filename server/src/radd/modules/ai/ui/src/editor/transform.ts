import type { EditorTransform } from "@radd/plugin-sdk";
import { streamSse } from "../sse";
import { AiEndpoint, aiErrorText, isAiGone } from "../transport";
import type { AiRun } from "./gate";
import { droppedCount, maskProtected, restoreProtected } from "./protect";

/** An AI run as an editor transform: the `POST /ai/editor/stream` request, with protected blocks
 *  masked before and restored after (`protect.ts`). The editor owns the review. */

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
      const body = {
        ...("actionId" in run ? { action_id: run.actionId } : { instruction: run.instruction }),
        document: document.masked,
        selection: selection.masked,
      };

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
      const dropped = droppedCount(text, kept);
      return { replacement: restoreProtected(text, kept), notes: dropped > 0 ? [droppedNote(dropped)] : [] };
    },
  };
}
