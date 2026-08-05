import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { registerDismiss } from "../lib/dismiss-stack";

interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** Wider panel for dense forms (New item). */
  wide?: boolean;
  /** Widest panel for design surfaces (the card designer, spec 109). */
  extraWide?: boolean;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Minimal centered modal: overlay, Escape / overlay-click / X to close. Focus
 * moves to the first form control on mount (the panel itself when there is
 * none), Tab and Shift-Tab wrap INSIDE the dialog — `aria-modal` used to be a
 * claim with no trap behind it, so Tab walked into the inert page (RADD-901)
 * — and focus returns to whatever opened the modal on close.
 */
export function Modal({ title, onClose, children, wide = false, extraWide = false }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Dismiss-stack, not a bare document listener: when the issue peek opens
    // over this modal, one Esc must close the topmost overlay only.
    return registerDismiss(() => {
      onClose();
      return true;
    });
  }, [onClose]);

  // Focus lifecycle runs ONCE per modal, not per render: `onClose` is usually
  // an inline arrow, and keying this effect on it would restore-then-steal
  // focus on every parent render.
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const panel = panelRef.current;
    (panel?.querySelector<HTMLElement>("input, select, textarea, button") ?? panel)?.focus();

    // The trap: Tab from the last focusable wraps to the first and vice
    // versa; a focus that escaped entirely (backdrop mousedown) re-enters at
    // the edge. The list is queried per keystroke, so controls that mount or
    // disable while the dialog is open stay covered.
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || !panel) return;
      const focusables = [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
        (el) => el.offsetParent !== null || el === document.activeElement,
      );
      if (focusables.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;
      if (event.shiftKey) {
        if (active === first || !panel.contains(active)) {
          event.preventDefault();
          last.focus();
        }
      } else if (active === last || !panel.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      opener?.focus();
    };
  }, []);

  return (
    <div
      className={
        "fixed inset-0 z-50 flex items-start justify-center bg-black/60 animate-fade-in " +
        (wide || extraWide ? "py-[8vh]" : "pt-[18vh]")
      }
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={
          "w-full animate-overlay-in rounded-xl border border-subtle bg-surface shadow-modal outline-none " +
          (extraWide
            ? "max-w-3xl max-h-full overflow-y-auto"
            : wide
              ? "max-w-xl max-h-full overflow-y-auto"
              : "max-w-md")
        }
      >
        <div className="flex items-center justify-between border-b border-subtle px-4 py-3">
          <h2 className="text-sm font-semibold text-heading">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg focus-visible:outline-2 focus-visible:outline-focus cursor-pointer"
          >
            <X size={16} />
          </button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}
