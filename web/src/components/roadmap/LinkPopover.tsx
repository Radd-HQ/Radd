import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import { ItemLinkType } from "../../lib/types";

/**
 * Floating link-type popover (spec 78), anchored at a drop/click point. Two
 * lives: after a ○-handle drop it CREATES a link — Blocks is the highlighted
 * default (Enter applies it, Esc cancels); clicked on an existing connector it
 * EDITS — the current type is highlighted, picking another retypes
 * (delete + re-create upstream), and a red "Remove link" deletes the edge.
 * Presentation only — the caller owns every mutation.
 */

/** The user-addable link types, in display order (mentions are auto-derived). */
const TYPE_CHOICES: { type: string; label: string }[] = [
  { type: ItemLinkType.blocks, label: "Blocks" },
  { type: ItemLinkType.relates, label: "Relates" },
  { type: ItemLinkType.duplicates, label: "Duplicates" },
];

const POPOVER_WIDTH = 208;

export interface LinkPopoverProps {
  x: number;
  y: number;
  sourceKey: string;
  targetKey: string;
  /** The existing link's type (edit mode); undefined = creating a new link. */
  currentType?: string;
  /** Create: POST with this type. Edit: retype (delete + re-create). */
  onPick: (type: string) => void;
  /** Edit mode only — DELETE the link. */
  onRemove?: () => void;
  onClose: () => void;
}

export function LinkPopover({
  x,
  y,
  sourceKey,
  targetKey,
  currentType,
  onPick,
  onRemove,
  onClose,
}: LinkPopoverProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: x, top: y });
  const creating = currentType === undefined;
  const highlighted = currentType ?? ItemLinkType.blocks;

  // Clamp into the viewport once measured (ContextMenu idiom).
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
      // Enter = the default choice while creating (spec 78).
      if (event.key === "Enter" && creating) {
        event.preventDefault();
        onPick(ItemLinkType.blocks);
      }
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
  }, [onClose, onPick, creating]);

  return (
    <div
      ref={rootRef}
      role="dialog"
      aria-label={creating ? "Choose link type" : "Edit link"}
      style={{ left: pos.left, top: pos.top, width: POPOVER_WIDTH }}
      className="fixed z-50 rounded-lg border border-strong bg-surface p-2 shadow-xl shadow-black/40"
    >
      <p className="mb-1.5 px-0.5 font-mono text-[11px] text-fg-secondary">
        {sourceKey} <span className="text-fg-faint">→</span> {targetKey}
      </p>
      <div className="flex gap-1">
        {TYPE_CHOICES.map(({ type, label }) => (
          <button
            key={type}
            type="button"
            onClick={() => {
              // Re-picking the current type is a no-op — just close.
              if (!creating && type === currentType) onClose();
              else onPick(type);
            }}
            className={`flex-1 rounded-md border px-1.5 py-1 text-[11px] cursor-pointer ${
              type === highlighted
                ? "border-accent/60 bg-accent/15 text-accent-text"
                : "border-strong text-fg hover:border-emphasis hover:text-heading"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="mt-1.5 px-0.5 text-[10px] leading-snug text-fg-faint">
        {creating ? "Enter = Blocks · Esc cancels" : "Pick a type to change the link"}
      </p>
      {!creating && onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="mt-1.5 flex w-full items-center justify-center gap-1.5 rounded-md border border-red-500/40 px-1.5 py-1 text-[11px] text-red-400 hover:border-red-500/70 hover:bg-red-500/10 cursor-pointer"
        >
          <Trash2 size={12} aria-hidden />
          Remove link
        </button>
      )}
    </div>
  );
}
