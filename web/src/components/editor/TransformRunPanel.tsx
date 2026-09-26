import { useEffect, useRef } from "react";
import { Check, ChevronLeft, ChevronRight, Loader2, Sparkles, Undo2, X } from "lucide-react";
import { Button } from "../Button";

/**
 * The transform run band: streaming progress, then Accept all / Reject all and a stepper over the
 * per-block pairs. It is editor chrome under the toolbar, not a floating panel: a document-wide run
 * has no selection to anchor to, and a floating box over a viewport-tall editor covers the diff.
 */

/** What the run is doing. Whether any text has arrived is the only progress signal a stream
 * actually gives us — inventing finer phases would be narration, not information. */
export const TransformRunStatus = {
  streaming: "streaming",
  reviewing: "reviewing",
} as const;

type TransformRunStatusValue = (typeof TransformRunStatus)[keyof typeof TransformRunStatus];

export interface TransformRunView {
  /** The transform's label — an action's name, or the typed instruction. */
  label: string;
  status: TransformRunStatusValue;
  /** The replacement so far. Empty until the first text lands. */
  text: string;
}

interface TransformRunPanelProps {
  run: TransformRunView;
  /** Accept/Reject pairs still pending (review only). */
  changes: number;
  /** Which pair the person has stepped to, or -1 for none yet. */
  current: number;
  onNavigate: (index: number) => void;
  onStop: () => void;
  onAcceptAll: () => void;
  onRejectAll: () => void;
  /** RADD-1274: open inline comments whose passages the proposed document no longer contains —
   *  what accepting it would detach. */
  detached?: number;
  /** Resolve those comments when the review ends with their passages gone. */
  resolveDetached?: boolean;
  onResolveDetachedChange?: (resolve: boolean) => void;
  /** What the transform said about its result (e.g. blocks it had to keep). */
  notes?: string[];
}

export function TransformRunPanel({
  run,
  changes,
  current,
  onNavigate,
  onStop,
  onAcceptAll,
  onRejectAll,
  detached = 0,
  resolveDetached = true,
  onResolveDetachedChange,
  notes = [],
}: TransformRunPanelProps) {
  const streaming = run.status === TransformRunStatus.streaming;
  const previewRef = useRef<HTMLDivElement>(null);

  // Follow the stream. Without this the preview shows the first two lines and then sits still
  // for the rest of the run, which reads as a stall.
  useEffect(() => {
    const preview = previewRef.current;
    if (preview) preview.scrollTop = preview.scrollHeight;
  }, [run.text]);

  return (
    <div
      data-editor-run-panel
      {...(streaming ? { "data-editor-run-streaming": true } : {})}
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
          data-editor-run-preview
          className="max-h-16 overflow-y-auto whitespace-pre-wrap break-words rounded border border-subtle bg-base px-2 py-1.5 text-[11px] leading-relaxed text-fg-secondary"
        >
          {run.text || <span className="text-fg-faint">Waiting for the first words…</span>}
        </div>
      ) : (
        // The diff plugin's filterTransaction drops every document transaction while a review is
        // open, so typing genuinely does nothing. Saying so beats letting someone conclude the
        // editor broke.
        <div className="flex flex-col gap-1 text-[11px] text-fg-muted">
          <p>
            Editing is paused until you accept or reject. Use the buttons beside a change to decide
            that one on its own.
          </p>
          {notes.map((note) => (
            <p key={note} data-editor-run-note>
              {note}
            </p>
          ))}
          {detached > 0 && (
            // RADD-1274: the review names the comments it is about to strand. Their passages go
            // with the text; the comments do not — RADD-726 never resolves one on anyone's behalf
            // — unless the person says so here, in the same click that removes the passages.
            <label data-editor-detached-comments className="flex items-center gap-1.5 text-fg">
              <input
                type="checkbox"
                checked={resolveDetached}
                onChange={(event) => onResolveDetachedChange?.(event.target.checked)}
              />
              <span>
                {detached === 1
                  ? "Replaces the passage of 1 open comment — resolve it when accepting"
                  : `Replaces the passages of ${detached} open comments — resolve them when accepting`}
              </span>
            </label>
          )}
        </div>
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
