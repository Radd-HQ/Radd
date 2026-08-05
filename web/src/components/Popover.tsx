import { useEffect, type ReactNode } from "react";
import { registerDismiss } from "../lib/dismiss-stack";

interface PopoverProps {
  open: boolean;
  onClose: () => void;
  /** Accessible name for the dialog panel. */
  label: string;
  /** Which edge of the trigger the panel hangs from. */
  align?: "start" | "end";
  /** Panel width/padding/scrolling — the frame (border, surface, shadow,
   * entrance) is this component's job. */
  className?: string;
  children: ReactNode;
}

/**
 * A click-away popover for custom content (RADD-901): the fixed-inset backdrop
 * + absolute panel + Escape-to-close pattern that DisplayMenu, WipLimitMenu
 * and BreadcrumbCrumb each rebuilt by hand — none of them with Escape, and
 * each with its own borders and shadows. `DropdownMenu` stays the right tool
 * for action lists; this is the primitive for "a small form or list in a
 * dismissable panel".
 *
 * Render it beside the trigger inside a `relative` wrapper. Escape goes
 * through the dismiss-stack, so a popover over a modal closes top-first.
 */
export function Popover({
  open,
  onClose,
  label,
  align = "end",
  className = "",
  children,
}: PopoverProps) {
  useEffect(() => {
    if (!open) return;
    return registerDismiss(() => {
      onClose();
      return true;
    });
  }, [open, onClose]);

  if (!open) return null;
  return (
    <>
      <div className="fixed inset-0 z-30" onMouseDown={onClose} aria-hidden />
      <div
        role="dialog"
        aria-label={label}
        className={
          "absolute top-full z-40 mt-1 rounded-lg border border-subtle bg-surface " +
          "shadow-pop animate-menu-in " +
          (align === "end" ? "right-0 " : "left-0 ") +
          className
        }
      >
        {children}
      </div>
    </>
  );
}
