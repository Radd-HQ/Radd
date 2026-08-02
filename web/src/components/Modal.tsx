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

/**
 * Minimal centered modal: overlay, Escape / overlay-click / X to close,
 * focuses its first form control on mount.
 */
export function Modal({ title, onClose, children, wide = false, extraWide = false }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Dismiss-stack, not a bare document listener: when the issue peek opens
    // over this modal, one Esc must close the topmost overlay only.
    const unregister = registerDismiss(() => {
      onClose();
      return true;
    });
    panelRef.current
      ?.querySelector<HTMLElement>("input, select, textarea, button")
      ?.focus();
    return unregister;
  }, [onClose]);

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
        className={
          "w-full animate-overlay-in rounded-xl border border-subtle bg-surface shadow-modal " +
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
