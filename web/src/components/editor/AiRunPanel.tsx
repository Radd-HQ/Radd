import { useEffect, useRef } from "react";
import { Check, ChevronLeft, ChevronRight, Loader2, Sparkles, Undo2, X } from "lucide-react";
import { Button } from "../Button";

/**
 * The AI run band (RADD-762) — one surface for the whole life of a run.
 *
 * What it replaces was a 224px strip positioned at `selection.left - 110`,
 * which for a run with no selection (the toolbar's AI button, and the read-mode
 * hand-off that is "Summarize" in edit mode) meant `x: -110`: painted, correct,
 * and off the left edge of the screen. That is why a document-wide transform
 * read as no feedback at all.
 *
 * The fix is not a better offset. A floating panel was tried first and the
 * screenshot settled it: anchored to the editor's bottom-right it covered the
 * second and third paragraphs of the very diff it was asking about, and no
 * clamp fixes that — an editor as tall as the viewport leaves a floating box
 * nowhere to go. So this is not floating at all. It is a band in the editor's
 * own chrome, directly under the toolbar, which takes layout space instead of
 * borrowing it: it cannot cover the document, it needs no measurement, no
 * viewport clamp and no scroll listener, and it is on screen exactly when the
 * editor is.
 *
 * It also carries the two things a per-block review cannot: what is happening
 * while nothing has arrived yet, and a way out of a twenty-button review in one
 * click. The per-block pairs stay — granular review is the point of the
 * decoration fork — but they stop being the only exit.
 */

/** What the run is doing. `sending`/`writing` are derived from whether any text
 * has arrived, which is the only progress signal a token stream actually gives
 * us — inventing finer phases would be narration, not information. */
export const AiRunStatus = {
  streaming: "streaming",
  reviewing: "reviewing",
} as const;

export type AiRunStatusValue = (typeof AiRunStatus)[keyof typeof AiRunStatus];

export interface AiRunView {
  /** The action's name, or the freeform prompt — `AiRun.label`, which until now
   *  was documented as "the label the streaming indicator shows" and passed to
   *  nothing. */
  label: string;
  status: AiRunStatusValue;
  /** Result markdown so far. Empty until the first token lands. */
  text: string;
}

interface AiRunPanelProps {
  run: AiRunView;
  /** Accept/Reject pairs still pending (review only). */
  changes: number;
  /** Which pair the person has stepped to, or -1 for none yet. */
  current: number;
  onNavigate: (index: number) => void;
  onStop: () => void;
  onAcceptAll: () => void;
  onRejectAll: () => void;
}

export function AiRunPanel({
  run,
  changes,
  current,
  onNavigate,
  onStop,
  onAcceptAll,
  onRejectAll,
}: AiRunPanelProps) {
  const streaming = run.status === AiRunStatus.streaming;
  const previewRef = useRef<HTMLDivElement>(null);

  // Follow the stream. Without this the preview shows the first two lines and
  // then sits still for the rest of the run, which reads as a stall.
  useEffect(() => {
    const preview = previewRef.current;
    if (preview) preview.scrollTop = preview.scrollHeight;
  }, [run.text]);

  return (
    <div
      data-ai-run-panel
      // The selector the RADD-753 proof waits on. It named the streaming state,
      // not the old widget, so it keeps meaning what it meant.
      {...(streaming ? { "data-ai-streaming": true } : {})}
      className="flex flex-col gap-1.5 border-b border-subtle bg-elevated px-2.5 py-2 animate-fade-in"
    >
      <div className="flex items-center gap-2">
        <Sparkles size={13} aria-hidden className="shrink-0 text-accent-text" />
        <span
          className="shrink-0 max-w-[40%] truncate text-xs font-medium text-heading"
          title={run.label}
        >
          {run.label}
        </span>
        {streaming ? (
          <>
            <span
              role="status"
              className="flex min-w-0 flex-1 items-center gap-1.5 text-[11px] text-fg-secondary"
            >
              <Loader2 size={11} aria-hidden className="shrink-0 animate-spin text-accent-text" />
              {run.text === "" ? "Reading your text…" : "Writing the result…"}
            </span>
            <button
              type="button"
              onClick={onStop}
              aria-label="Stop"
              title="Stop"
              className="shrink-0 cursor-pointer rounded p-0.5 text-fg-muted hover:bg-overlay hover:text-heading focus-visible:outline-2 focus-visible:outline-focus"
            >
              <X size={13} aria-hidden />
            </button>
          </>
        ) : (
          <>
            <span role="status" className="min-w-0 flex-1 truncate text-[11px] text-fg-secondary">
              {changes === 1 ? "1 change to review" : `${changes} changes to review`}
            </span>
            {changes > 1 && (
              <div className="flex shrink-0 items-center gap-0.5">
                <StepButton
                  label="Previous change"
                  onClick={() => onNavigate(current - 1)}
                  icon={<ChevronLeft size={12} aria-hidden />}
                />
                <span className="tabular-nums text-[10px] text-fg-muted">
                  {current < 0 ? "—" : current + 1}/{changes}
                </span>
                <StepButton
                  label="Next change"
                  onClick={() => onNavigate(current + 1)}
                  icon={<ChevronRight size={12} aria-hidden />}
                />
              </div>
            )}
            <Button size="sm" onClick={onAcceptAll} className="shrink-0">
              <Check size={12} aria-hidden />
              Accept all
            </Button>
            <Button size="sm" variant="secondary" onClick={onRejectAll} className="shrink-0">
              <Undo2 size={12} aria-hidden />
              Reject all
            </Button>
          </>
        )}
      </div>

      {streaming ? (
        <div
          ref={previewRef}
          data-ai-run-preview
          className="max-h-16 overflow-y-auto whitespace-pre-wrap break-words rounded border border-subtle bg-base px-2 py-1.5 text-[11px] leading-relaxed text-fg-secondary"
        >
          {run.text || <span className="text-fg-faint">Waiting for the first words…</span>}
        </div>
      ) : (
        // The diff plugin's filterTransaction drops every document transaction
        // while a review is open, so typing genuinely does nothing. Saying so
        // beats letting someone conclude the editor broke.
        <p className="text-[11px] text-fg-muted">
          Editing is paused until you accept or reject. Use the buttons beside a change to decide
          that one on its own.
        </p>
      )}
    </div>
  );
}

function StepButton({
  label,
  icon,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="cursor-pointer rounded p-0.5 text-fg-muted hover:bg-overlay hover:text-heading focus-visible:outline-2 focus-visible:outline-focus"
    >
      {icon}
    </button>
  );
}
