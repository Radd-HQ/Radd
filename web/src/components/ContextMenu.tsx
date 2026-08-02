import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Check, ChevronRight, type LucideIcon } from "lucide-react";

/**
 * Generic right-click context menu (spec 24): a fixed popover at the cursor with
 * flat actions, separators, and hover flyout submenus. Closes on outside click,
 * Esc, or scroll. Presentation only — callers pass the action tree.
 */
export type MenuNode =
  | {
      kind: "action";
      label: string;
      icon?: LucideIcon;
      onSelect: () => void;
      danger?: boolean;
      disabled?: boolean;
      checked?: boolean;
      /** Tooltip (title attr) — used to explain WHY a disabled entry is disabled. */
      hint?: string;
    }
  | { kind: "submenu"; label: string; icon?: LucideIcon; items: MenuNode[]; disabled?: boolean }
  | { kind: "separator" };

interface ContextMenuProps {
  x: number;
  y: number;
  items: MenuNode[];
  onClose: () => void;
}

const MENU_WIDTH = 224;

export function ContextMenu({ x, y, items, onClose }: ContextMenuProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: x, top: y });

  // Clamp into the viewport once measured.
  useLayoutEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const left = Math.min(x, window.innerWidth - rect.width - 8);
    const top = Math.min(y, window.innerHeight - rect.height - 8);
    setPos({ left: Math.max(8, left), top: Math.max(8, top) });
  }, [x, y]);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onClose, true);
    window.addEventListener("resize", onClose);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onClose, true);
      window.removeEventListener("resize", onClose);
    };
  }, [onClose]);

  return (
    <div
      ref={rootRef}
      role="menu"
      style={{ left: pos.left, top: pos.top, width: MENU_WIDTH }}
      className="fixed z-50"
    >
      <MenuPanel items={items} onClose={onClose} nearRightEdge={x > window.innerWidth - MENU_WIDTH * 2} />
    </div>
  );
}

function MenuPanel({
  items,
  onClose,
  nearRightEdge,
  scrollable = false,
}: {
  items: MenuNode[];
  onClose: () => void;
  nearRightEdge: boolean;
  /** Cap the height and scroll. Set on SUBMENU panels, whose contents are
   *  open-ended (every cycle, every label…) — the cycle list ran 90+ rows and
   *  simply overflowed off-screen with no way to reach the bottom. NOT set on
   *  the root panel: `overflow` there would clip the submenu flyouts, which
   *  are absolutely positioned outside it. Safe because no submenu contains
   *  another submenu. */
  scrollable?: boolean;
}) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  return (
    <ul
      className={
        "animate-menu-in rounded-lg border border-strong bg-surface py-1 shadow-pop " +
        (scrollable ? "max-h-[min(60vh,20rem)] overflow-y-auto overscroll-contain" : "")
      }
    >
      {items.map((node, index) => {
        if (node.kind === "separator") {
          return <li key={`sep-${index}`} className="my-1 h-px bg-elevated" aria-hidden />;
        }
        if (node.kind === "submenu") {
          const open = openIndex === index;
          return (
            <li
              key={node.label}
              className="relative"
              onMouseEnter={() => !node.disabled && setOpenIndex(index)}
              onMouseLeave={() => setOpenIndex((i) => (i === index ? null : i))}
            >
              <button
                type="button"
                disabled={node.disabled}
                aria-haspopup="menu"
                aria-expanded={open}
                className={rowClass(false, node.disabled)}
              >
                {node.icon && <node.icon size={14} className="shrink-0 text-fg-secondary" aria-hidden />}
                <span className="flex-1 truncate">{node.label}</span>
                <ChevronRight size={13} className="shrink-0 text-fg-muted" aria-hidden />
              </button>
              {open && (
                <div
                  className={
                    "absolute top-0 " + (nearRightEdge ? "right-full pr-1" : "left-full pl-1")
                  }
                  style={{ width: MENU_WIDTH }}
                >
                  <MenuPanel
                    items={node.items}
                    onClose={onClose}
                    nearRightEdge={nearRightEdge}
                    scrollable
                  />
                </div>
              )}
            </li>
          );
        }
        return (
          <li key={node.label}>
            <button
              type="button"
              disabled={node.disabled}
              title={node.hint}
              onClick={() => {
                node.onSelect();
                onClose();
              }}
              className={rowClass(node.danger, node.disabled)}
            >
              {node.icon ? (
                <node.icon size={14} className="shrink-0 text-fg-secondary" aria-hidden />
              ) : (
                <span className="w-3.5 shrink-0" aria-hidden />
              )}
              <span className="flex-1 truncate">{node.label}</span>
              {node.checked && <Check size={13} className="shrink-0 text-accent-text" aria-hidden />}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function rowClass(danger?: boolean, disabled?: boolean): string {
  return (
    "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[13px] " +
    (disabled
      ? "cursor-not-allowed text-fg-faint "
      : "cursor-pointer hover:bg-elevated focus-visible:bg-elevated focus-visible:outline-none ") +
    (danger && !disabled ? "text-red-400" : "text-fg")
  );
}
