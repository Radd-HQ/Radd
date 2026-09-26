import type { DecorationAttrs } from "prosemirror-view";
import { safeCursorColor } from "./presence-color";

/**
 * Remote cursor/selection builders replacing y-prosemirror's: upstream appends a hex alpha to the
 * colour (valid only on 6-digit hex; ours are token refs), so the colour rides `--collab-color` +
 * `color-mix`. The value is a peer's data — only `safeCursorColor` output reaches a style. Inline
 * styles because a remote's stylesheet is not loaded; DOM/class names stay upstream's.
 */
const CURSOR_CLASS = "ProseMirror-yjs-cursor";
const SELECTION_CLASS = "ProseMirror-yjs-selection";
const COLOR_PROPERTY = "--collab-color";
const COLOR = `var(${COLOR_PROPERTY}, var(--accent-fill))`;

const CURSOR_STYLE = [
  "position: relative", "margin-left: -1px", "margin-right: -1px",
  `border-left: 2px solid ${COLOR}`, "border-right: none", "word-break: normal", "pointer-events: none",
].join(";");

// Label text sits on the peer's own fill, a non-themed surface — the same
// deliberate exception Avatar makes with `text-white`.
const LABEL_STYLE = [
  "position: absolute", "top: -1.3em", "left: -2px", "padding: 0 5px",
  "border-radius: var(--radius-md) var(--radius-md) var(--radius-md) 0",
  `background: ${COLOR}`, "color: var(--color-white)", "font-size: 10px", "font-weight: 600",
  "line-height: 1.5", "white-space: nowrap", "user-select: none",
].join(";");

interface CursorUser {
  name?: unknown;
  color?: unknown;
}

export function cursorBuilder(user: CursorUser): HTMLElement {
  const cursor = document.createElement("span");
  cursor.classList.add(CURSOR_CLASS);
  cursor.style.cssText = CURSOR_STYLE;
  cursor.style.setProperty(COLOR_PROPERTY, safeCursorColor(user.color));
  const label = document.createElement("div");
  label.style.cssText = LABEL_STYLE;
  label.textContent = typeof user.name === "string" ? user.name : "";
  // Word-joiners on either side keep the caret from breaking a word in two
  // visually — the same trick upstream's builder uses.
  cursor.append("⁠", label, "⁠");
  return cursor;
}

export function selectionBuilder(user: CursorUser): DecorationAttrs {
  const color = safeCursorColor(user.color);
  return {
    class: SELECTION_CLASS,
    style: `${COLOR_PROPERTY}: ${color}; background: color-mix(in srgb, ${COLOR} 22%, transparent)`,
  };
}
