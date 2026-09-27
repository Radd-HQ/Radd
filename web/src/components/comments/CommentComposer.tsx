import { useEffect, useRef } from "react";
import { MessageSquare, MessagesSquare, Send } from "lucide-react";
import { CommentComposerMode, type CommentComposerModeValue, type CommentComposerProps } from "@radd/plugin-sdk";
import { Button } from "../Button";
import { escapeBelongsInside } from "./escape";
import { SegmentedChoice } from "./SegmentedChoice";

/** Said on the Start thread button and beside the Thread mode: what makes a thread worth starting. */
export const THREAD_HINT = "A thread can be resolved: use it for a question that needs an answer";

const MODES = [
  { value: CommentComposerMode.comment, label: "Comment" },
  { value: CommentComposerMode.thread, label: "Thread" },
] as const;

/** The row button each mode opens from — and returns focus to when the composer closes. */
const OPENER: Record<CommentComposerModeValue, string> = {
  [CommentComposerMode.comment]: "[data-open-comment]",
  [CommentComposerMode.thread]: "[data-start-thread]",
};

/**
 * A discussion's composer, on issues and pages alike (RADD-1448): hidden until asked for. Closed,
 * it is two buttons — Comment and Start thread. Open, a Comment | Thread switch (a wrong choice
 * needs no Cancel), the surface's `controls` and `children` (audience, canned responses, the
 * editor), and one submit whose words follow the mode and audience. Cancel and Escape close it and
 * the caller keeps the draft; focus goes back to the button the composer opened from.
 */
export function CommentComposer({
  mode,
  onMode,
  submitLabel,
  canSubmit,
  pending = false,
  error,
  onSubmit,
  controls,
  children,
}: CommentComposerProps) {
  const root = useRef<HTMLDivElement>(null);
  const returnTo = useRef<CommentComposerModeValue | null>(null);
  useEffect(() => {
    if (mode !== null || !returnTo.current) return;
    root.current?.querySelector<HTMLElement>(OPENER[returnTo.current])?.focus();
    returnTo.current = null;
  }, [mode]);

  if (mode === null) {
    return (
      <div ref={root} className="flex flex-wrap items-center gap-2" data-comment-composer="closed">
        <Button data-open-comment onClick={() => onMode(CommentComposerMode.comment)}>
          <MessageSquare size={13} aria-hidden />
          Comment
        </Button>
        <Button variant="secondary" data-start-thread title={THREAD_HINT}
          onClick={() => onMode(CommentComposerMode.thread)}>
          <MessagesSquare size={13} aria-hidden />
          Start thread
        </Button>
      </div>
    );
  }

  // Closing from inside (Cancel, Escape, a post that lands) hands focus back to the row.
  const leaving = () => { returnTo.current = mode; };
  const cancel = () => { leaving(); onMode(null); };
  const submit = () => {
    if (!canSubmit || pending) return;
    leaving();
    onSubmit();
  };
  return (
    <div ref={root} data-comment-composer="open" data-mode={mode}>
      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => { event.preventDefault(); submit(); }}
        onKeyDown={(event) => {
          // The editor's Cmd/Ctrl+Enter posts without the submit button: note where focus returns.
          if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) leaving();
          if (event.key !== "Escape" || escapeBelongsInside(event)) return;
          event.preventDefault();
          event.stopPropagation(); // the composer, not the peek or popover around it
          cancel();
        }}
      >
        <div className="flex flex-wrap items-center gap-2">
          <SegmentedChoice label="Post as" value={mode} options={MODES} onChange={onMode} data-composer-mode={mode} />
          {controls}
          {mode === CommentComposerMode.thread && (
            <span className="text-[11px] text-fg-muted" data-thread-hint>{THREAD_HINT}</span>
          )}
        </div>
        {children}
        {error && <p role="alert" className="text-xs text-status-danger-ink">{error}</p>}
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={cancel} data-composer-cancel>
            Cancel
          </Button>
          <Button type="submit" disabled={!canSubmit || pending}>
            <Send size={13} aria-hidden />
            {pending ? "Posting…" : submitLabel}
          </Button>
        </div>
      </form>
    </div>
  );
}
