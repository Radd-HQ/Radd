import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useDialogFocus } from "../lib/dialog-focus";
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

/**
 * Minimal centered modal: overlay, Escape / overlay-click / X to close. Focus
 * moves to the first form control on mount (the panel itself when there is
 * none), Tab and Shift-Tab wrap INSIDE the dialog — `aria-modal` used to be a
 * claim with no trap behind it, so Tab walked into the inert page (RADD-901)
 * — and focus returns to whatever opened the modal on close.
 */
export function Modal({ title, onClose, children, wide = false, extraWide = false }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    // Dismiss-stack, not a bare document listener: when the issue peek opens
    // over this modal, one Esc must close the topmost overlay only.
    return registerDismiss(() => {
      closeRef.current();
      return true;
    });
  }, []);

  useDialogFocus(panelRef);

  // A transformed toolbar/animated ancestor changes the containing block of
  // fixed descendants. Portals keep the overlay anchored to the viewport.
  return createPortal(
    <div
      className={
        "fixed inset-0 z-50 px-2 sm:px-4 flex items-start justify-center bg-black/60 animate-fade-in " +
        (wide || extraWide ? "py-[8vh]" : "py-[4vh] sm:pt-[18vh]")
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
              : "max-w-md max-h-full overflow-y-auto")
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
    </div>, document.body
  );
}
