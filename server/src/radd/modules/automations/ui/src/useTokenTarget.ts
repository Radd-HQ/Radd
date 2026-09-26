/**
 * Where a clicked `{{token}}` lands: the text field focused LAST inside the inspector. `onFocusCapture`
 * because focus does not bubble; the write uses the native value setter + an `input` event, because
 * assigning `.value` leaves React state (and so the params) unchanged.
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
