import type { DecorationAttrs } from "@milkdown/kit/prose/view";
import { safeCursorColor } from "./presence-color";
import "./cursors.css";

/**
 * Remote cursor + selection chrome (spec 122), replacing y-prosemirror's
 * default builders for two reasons:
 *
 * - Upstream paints `background-color: ${color}70` — a hex alpha suffix that
 *   is only valid on a 6-digit hex. Our colours are token references, so the
 *   colour rides a custom property (`--collab-color`) and cursors.css does the
 *   mixing with `color-mix`, which works for any colour value.
 * - The value came from a peer's awareness state. It goes through
 *   `safeCursorColor` and `style.setProperty`, never string-built CSS.
 *
 * The DOM shape and class names are upstream's, so a future y-prosemirror
 * still styles what it expects to find.
 */
const CURSOR_CLASS = "ProseMirror-yjs-cursor";
const SELECTION_CLASS = "ProseMirror-yjs-selection";
const COLOR_PROPERTY = "--collab-color";

interface CursorUser {
  name?: unknown;
  color?: unknown;
}

export function cursorBuilder(user: CursorUser): HTMLElement {
  const cursor = document.createElement("span");
  cursor.classList.add(CURSOR_CLASS);
  cursor.style.setProperty(COLOR_PROPERTY, safeCursorColor(user.color));
  const label = document.createElement("div");
  label.textContent = typeof user.name === "string" ? user.name : "";
  // Word-joiners on either side keep the caret from breaking a word in two
  // visually — the same trick upstream's builder uses.
  cursor.append("⁠", label, "⁠");
  return cursor;
}

export function selectionBuilder(user: CursorUser): DecorationAttrs {
  return {
    class: SELECTION_CLASS,
    style: `${COLOR_PROPERTY}: ${safeCursorColor(user.color)}`,
  };
}
