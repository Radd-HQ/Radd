import { useRef } from "react";
import { createPortal } from "react-dom";
import { Slot, SlotId, type EditorHandle } from "@radd/plugin-sdk";
import type { SelectionRect } from "./selection-state";

/**
 * The `editor.selection.action` anchor: contributions' chrome over a text selection. The host places
 * it above the selection's midpoint and keeps it mounted while idle, so a contribution's open popover
 * survives the selection collapsing. A contribution reads `selection` (null while nothing is selected
 * or the editor is unfocused) and decides whether to show a trigger; nothing while a transform runs.
 */
export function SelectionActions({ rect, editor }: { rect: SelectionRect; editor: EditorHandle }) {
  // Where the last real selection was: a contribution's trigger is in-flow here, and an open
  // popover is its own (portaled) business.
  const placed = useRef({ left: 0, top: 0 });
  const live = !rect.empty && rect.focused;
  if (live) placed.current = { left: rect.left, top: rect.top };
  if (editor.busy) return null;
  return createPortal(
    <div
      data-editor-selection-actions
      style={{ position: "fixed", left: placed.current.left - 18, top: placed.current.top - 38 }}
      className="z-[58] flex items-center gap-1"
    >
      <Slot
        id={SlotId.editorSelectionAction}
        editor={editor}
        selection={live ? { from: rect.from, to: rect.to, left: rect.left, top: rect.top, bottom: rect.bottom } : null}
      />
    </div>,
    document.body,
  );
}
