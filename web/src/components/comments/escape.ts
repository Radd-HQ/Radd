import type { KeyboardEvent } from "react";
import { SLASH_RE, TRIGGER_RE } from "../editor/mention";

/** The mention picker reads this much text before the caret (mention.ts). */
const TRIGGER_WINDOW = 60;

/** Whether the rich editor's @ / # / `/` picker holds the caret: the picker's own test, on the DOM. */
function caretAfterTrigger(): boolean {
  const selection = window.getSelection();
  const anchor = selection?.anchorNode;
  if (!selection || !selection.isCollapsed || !anchor) return false;
  const block = (anchor instanceof Element ? anchor : anchor.parentElement)
    ?.closest("p, h1, h2, h3, h4, h5, h6, td, th");
  if (!block) return false;
  const range = document.createRange();
  range.setStart(block, 0);
  range.setEnd(anchor, selection.anchorOffset);
  const text = range.toString();
  const before = text.slice(-TRIGGER_WINDOW);
  return (text.length <= TRIGGER_WINDOW && SLASH_RE.test(before)) || TRIGGER_RE.test(before);
}

/**
 * Whether an Escape pressed inside a composer was meant for something IN it rather than for the
 * composer (RADD-1448): a menu or picker that used it marks it handled; a code block's editor uses
 * it to step out; and the rich editor marks EVERY Escape handled, so there the question is whether
 * its mention picker holds the caret. Anything else closes the composer.
 */
export function escapeBelongsInside(event: KeyboardEvent<Element>): boolean {
  const target = event.target instanceof Element ? event.target : null;
  if (target?.closest(".cm-editor")) return true;
  if (target?.closest(".ProseMirror")) return caretAfterTrigger();
  return event.defaultPrevented;
}
