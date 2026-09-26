import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Sparkles } from "lucide-react";
import type { EditorSelection, EditorSelectionActionProps } from "@radd/plugin-sdk";
import { AiActionPicker } from "./ActionPicker";
import { useEditorAi } from "./gate";
import { aiTransform } from "./transform";

/**
 * Ask AI over a selection (`editor.selection.action`). Progress is not shown here but in the
 * editor's run band (RADD-762): chrome anchored to the selection disappears when there is none.
 */
export function AiSelectionAction({ editor, selection }: EditorSelectionActionProps) {
  const ai = useEditorAi();
  // The selection WHEN THIS OPENED: the picker's input takes focus and collapses the live
  // selection, which silently turned every selection run into a document-wide one.
  const [anchor, setAnchor] = useState<EditorSelection | null>(null);
  const open = anchor !== null;

  // A NEW selection while the picker is open belongs to whatever the person is doing now; close
  // rather than run against a stale range.
  useEffect(() => {
    if (selection) setAnchor(null);
  }, [selection?.from, selection?.to]);

  if (!ai || editor.busy) return null;
  if (open && anchor) {
    return createPortal(
      <>
        <div className="fixed inset-0 z-[59]" onMouseDown={() => setAnchor(null)} />
        <div
          style={{ position: "fixed", left: Math.min(anchor.left - 144, window.innerWidth - 300), top: anchor.bottom + 8 }}
          className="z-[60] w-72 rounded-md border border-strong bg-surface p-1.5 shadow-pop animate-menu-in"
          data-ai-selection-menu
        >
          <AiActionPicker
            actions={ai.actions}
            onPick={(run) => {
              const range = { from: anchor.from, to: anchor.to };
              setAnchor(null);
              editor.transform(aiTransform(run), range);
            }}
            autoFocus
          />
        </div>
      </>,
      document.body,
    );
  }
  if (!selection) return null;
  return (
    <button
      type="button"
      data-ai-selection-button
      aria-label="Ask AI about the selection"
      title="Ask AI"
      // Keeps the highlight while opening; nothing depends on it — the range travels in `anchor`.
      onMouseDown={(event) => event.preventDefault()}
      onClick={() => setAnchor(selection)}
      className="inline-flex h-7 items-center gap-1 rounded-md border border-strong bg-surface px-2 text-[11px] text-fg-secondary shadow-pop transition-colors hover:text-heading focus-visible:outline-2 focus-visible:outline-focus cursor-pointer animate-fade-in"
    >
      <Sparkles size={13} className="text-accent-text" />
      Ask AI
    </button>
  );
}
