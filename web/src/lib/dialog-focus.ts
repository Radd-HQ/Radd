import { useEffect, type RefObject } from "react";

const panels: HTMLElement[] = [];
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [contenteditable="true"], [tabindex]:not([tabindex="-1"])';

/** Only the most recently opened dialog owns Tab; closing restores its opener. */
export function useDialogFocus(ref: RefObject<HTMLElement | null>, open = true) {
  useEffect(() => {
    const panel = ref.current;
    if (!open || !panel) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panels.push(panel);
    (panel.querySelector<HTMLElement>("input, select, textarea, button") ?? panel).focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || event.defaultPrevented || panels.at(-1) !== panel) return;
      const controls = [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(el => el.getClientRects().length > 0);
      const first = controls[0] ?? panel;
      const last = controls.at(-1) ?? panel;
      const active = document.activeElement;
      if (!panel.contains(active) || (event.shiftKey ? active === first : active === last) || controls.length === 0) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      const wasTop = panels.at(-1) === panel;
      panels.splice(panels.indexOf(panel), 1);
      document.removeEventListener("keydown", keydown);
      if (wasTop && opener?.isConnected) opener.focus();
    };
  }, [ref, open]);
}
