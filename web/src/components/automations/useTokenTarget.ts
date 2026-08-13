/**
 * Where a clicked `{{token}}` lands (spec 120).
 *
 * The token list sits below a form whose fields are built by four different
 * components, so "insert into the field" cannot be a prop threaded through all
 * of them — it would mean every param editor learning about tokens, including
 * the ones generated from a JSON Schema. Instead the inspector remembers which
 * text field was focused LAST and writes there.
 *
 * `onFocusCapture` rather than `onFocus`, because focus does not bubble; capture
 * is what lets one handler on the container see every field below it. And the
 * write goes through the native value setter plus a synthetic `input` event
 * rather than assigning `.value`: React's onChange is wired to the input event,
 * and a plain assignment updates the DOM node while leaving React's state — and
 * therefore the node's params — exactly as they were.
 */
import { useCallback, useRef } from "react";

type TextField = HTMLInputElement | HTMLTextAreaElement;

function isTextField(element: EventTarget | null): element is TextField {
  if (element instanceof HTMLTextAreaElement) return true;
  return element instanceof HTMLInputElement && element.type !== "checkbox";
}

export function useTokenTarget() {
  const target = useRef<TextField | null>(null);

  const onFocusCapture = useCallback((event: React.FocusEvent) => {
    if (isTextField(event.target)) target.current = event.target as TextField;
  }, []);

  const insert = useCallback((token: string) => {
    const field = target.current;
    if (!field || !field.isConnected) return;
    const prototype =
      field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
    const start = field.selectionStart ?? field.value.length;
    const end = field.selectionEnd ?? field.value.length;
    const next = `${field.value.slice(0, start)}${token}${field.value.slice(end)}`;
    setter?.call(field, next);
    field.dispatchEvent(new Event("input", { bubbles: true }));
    field.focus();
    const caret = start + token.length;
    field.setSelectionRange(caret, caret);
  }, []);

  return { onFocusCapture, insert };
}
