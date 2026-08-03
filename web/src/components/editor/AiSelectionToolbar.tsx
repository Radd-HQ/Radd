import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Sparkles } from "lucide-react";
import { AiActionPicker } from "./AiActionPicker";
import type { AiRun } from "./ai";
import type { SelectionRect } from "./selection-state";
import type { AiEditorAction } from "../../lib/types";

/**
 * The AI entry point over a selection — ours (RADD-753).
 *
 * It replaces a floating toolbar we did not control, whose only entry we used
 * was this one. Two states: a button while idle, and the action picker once
 * opened. The picker is the same component the toolbar's document-wide button
 * uses, so the curated list and the freeform prompt cannot drift between them.
 *
 * It no longer reports PROGRESS (RADD-762). It used to, and that was the bug:
 * the indicator was positioned off this component's selection rect, so every
 * run without a selection painted it off the left edge of the screen. Progress
 * belongs to the run, not to the selection — see `AiRunPanel`.
 */
export function AiSelectionToolbar({
  rect,
  actions,
  onRun,
  busy,
}: {
  rect: SelectionRect;
  actions: AiEditorAction[];
  /** The range is passed WITH the run, captured when this opened. */
  onRun: (run: AiRun, range: { from: number; to: number }) => void;
  /** A run or review already owns the editor — offering a second one would
   *  only earn a "finish the current review first" toast. */
  busy: boolean;
}) {
  // What was selected WHEN THIS OPENED, not what is selected now.
  //
  // Opening the picker necessarily moves focus out of the editor — its prompt
  // field is an <input> — which collapses the ProseMirror selection. Reading the
  // live selection at run time therefore turned every selection-scoped run into
  // a document-wide one, and did it silently. Capturing the anchor also lets the
  // surface stay put while someone types a prompt.
  const [anchor, setAnchor] = useState<SelectionRect | null>(null);
  const open = anchor !== null;

  // A NEW selection while the picker is open belongs to whatever the person is
  // doing now; close rather than run against a stale range.
  useEffect(() => {
    if (!rect.empty) setAnchor(null);
  }, [rect.from, rect.to]);

  if (busy) return null;
  if (!open && (rect.empty || !rect.focused)) return null;

  return createPortal(
    open && anchor ? (
      <>
        <div className="fixed inset-0 z-[59]" onMouseDown={() => setAnchor(null)} />
        <div
          style={{ position: "fixed", left: Math.min(anchor.left - 144, window.innerWidth - 300), top: anchor.bottom + 8 }}
          className="z-[60] w-72 rounded-md border border-strong bg-surface p-1.5 shadow-pop animate-menu-in"
          data-ai-selection-menu
        >
          <AiActionPicker
            actions={actions}
            onPick={(run) => {
              const range = { from: anchor.from, to: anchor.to };
              setAnchor(null);
              onRun(run, range);
            }}
            autoFocus
          />
        </div>
      </>
    ) : (
      <button
        type="button"
        data-ai-selection-button
        aria-label="Ask AI about the selection"
        title="Ask AI"
        style={{ position: "fixed", left: rect.left - 18, top: rect.top - 38 }}
        // The selection must survive opening this — a click that focuses the
        // button would otherwise collapse the very range the run applies to.
        // preventDefault is kept as a courtesy — it keeps the highlight visible
        // a moment longer — but nothing DEPENDS on it: the range travels in the
        // anchor, so a browser that focuses the button anyway cannot silently
        // widen the run to the whole document.
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => setAnchor(rect)}
        className="z-[58] inline-flex h-7 items-center gap-1 rounded-md border border-strong bg-surface px-2 text-[11px] text-fg-secondary shadow-pop transition-colors hover:text-heading focus-visible:outline-2 focus-visible:outline-focus cursor-pointer animate-fade-in"
      >
        <Sparkles size={13} className="text-accent-text" />
        Ask AI
      </button>
    ),
    document.body,
  );
}
