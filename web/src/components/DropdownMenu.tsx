import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type Ref } from "react";
import { MoreHorizontal, type LucideIcon } from "lucide-react";

/**
 * Trigger-anchored action menu (the "⋯"/chevron companion to ContextMenu):
 * a flat list of actions + separators in a small popover under/over the
 * trigger. Closes on outside click, Escape (focus returns to the trigger), or
 * resize — never on scroll, since the panel is anchored to the trigger and
 * travels with it; ArrowUp/Down move between items, Enter activates.
 * Presentation only — callers pass the action list.
 */
export type DropdownMenuItem =
  | {
      kind: "action";
      label: string;
      icon?: LucideIcon;
      onSelect: () => void;
      danger?: boolean;
      disabled?: boolean;
    }
  | { kind: "separator" };

export interface DropdownMenuTriggerProps {
  ref: Ref<HTMLButtonElement>;
  open: boolean;
  toggle: () => void;
}

interface DropdownMenuProps {
  items: DropdownMenuItem[];
  /** aria-label for the trigger and the menu. */
  label: string;
  /** Horizontal edge the panel aligns to (default: trigger's left edge). */
  align?: "start" | "end";
  /** Open below (default) or above the trigger. */
  side?: "bottom" | "top";
  /** Panel width utility (default w-48); use w-full to match the trigger. */
  widthClass?: string;
  /** Extra classes on the relative wrapper (e.g. margin). */
  className?: string;
  /** Custom trigger; defaults to a ⋯ icon button. */
  trigger?: (props: DropdownMenuTriggerProps) => ReactNode;
}

const ITEM_SELECTOR = 'button[role="menuitem"]:not(:disabled)';

export function DropdownMenu({
  items,
  label,
  align = "start",
  side = "bottom",
  widthClass = "w-48",
  className = "",
  trigger,
}: DropdownMenuProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLUListElement>(null);

  const close = (focusTrigger = false) => {
    setOpen(false);
    if (focusTrigger) triggerRef.current?.focus();
  };

  // Focus the first enabled item on open.
  useLayoutEffect(() => {
    if (open) panelRef.current?.querySelector<HTMLButtonElement>(ITEM_SELECTOR)?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (panelRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setOpen(false);
    };
    // No close-on-scroll: the panel is anchored to its trigger and travels
    // with it on page scroll.
    const onPassiveClose = () => setOpen(false);
    document.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("resize", onPassiveClose);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("resize", onPassiveClose);
    };
  }, [open]);

  const onMenuKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close(true);
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const buttons = Array.from(
      panelRef.current?.querySelectorAll<HTMLButtonElement>(ITEM_SELECTOR) ?? [],
    );
    if (buttons.length === 0) return;
    event.preventDefault();
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      event.key === "ArrowDown"
        ? (index + 1) % buttons.length
        : (index - 1 + buttons.length) % buttons.length;
    buttons[next].focus();
  };

  const triggerProps: DropdownMenuTriggerProps = {
    ref: triggerRef,
    open,
    toggle: () => setOpen((current) => !current),
  };

  return (
    <div className={`relative ${className}`}>
      {trigger ? (
        trigger(triggerProps)
      ) : (
        <button
          ref={triggerRef}
          type="button"
          onClick={triggerProps.toggle}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label={label}
          className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
        >
          <MoreHorizontal size={14} aria-hidden />
        </button>
      )}

      {open && (
        <ul
          ref={panelRef}
          role="menu"
          aria-label={label}
          onKeyDown={onMenuKeyDown}
          className={
            "absolute z-40 animate-menu-in rounded-lg border border-subtle bg-surface py-1 shadow-pop " +
            (side === "bottom" ? "top-full mt-1 " : "bottom-full mb-1 ") +
            (align === "end" ? "right-0 " : "left-0 ") +
            widthClass
          }
        >
          {items.map((item, index) =>
            item.kind === "separator" ? (
              <li key={`sep-${index}`} className="my-1 h-px bg-subtle" aria-hidden />
            ) : (
              <li key={item.label}>
                <button
                  type="button"
                  role="menuitem"
                  disabled={item.disabled}
                  onClick={() => {
                    item.onSelect();
                    close();
                  }}
                  className={
                    "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[13px] " +
                    (item.disabled
                      ? "cursor-not-allowed text-fg-faint "
                      : "cursor-pointer hover:bg-overlay focus-visible:bg-overlay focus-visible:outline-none ") +
                    (item.danger && !item.disabled ? "text-red-400" : "text-fg")
                  }
                >
                  {item.icon ? (
                    <item.icon size={14} className="shrink-0 text-fg-muted" aria-hidden />
                  ) : (
                    <span className="w-3.5 shrink-0" aria-hidden />
                  )}
                  <span className="flex-1 truncate">{item.label}</span>
                </button>
              </li>
            ),
          )}
        </ul>
      )}
    </div>
  );
}
