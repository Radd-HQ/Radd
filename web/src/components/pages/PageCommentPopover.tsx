import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { registerDismiss } from "../../lib/dismiss-stack";
import type { CommentPointer } from "./useCommentPointer";

/** Portalled outside the scrolling sidebar; never steals the editor's caret. */
export function PageCommentPopover({pointer, onClose, onKeep, onLeave, onPin, children}: {
  pointer: CommentPointer;
  onClose: () => void;
  onKeep: () => void;
  onLeave: () => void;
  onPin: () => void;
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({left: pointer.x, top: pointer.y});
  useLayoutEffect(() => {
    const place = () => {
      const rect = panel.current?.getBoundingClientRect();
      if (!rect) return;
      const left = Math.max(8, Math.min(pointer.x + 12, innerWidth - rect.width - 8));
      const below = pointer.y + 16;
      const top = Math.max(8, Math.min(below + rect.height <= innerHeight - 8 ? below : pointer.y - rect.height - 12,
        innerHeight - rect.height - 8));
      setPosition(previous => previous.left === left && previous.top === top ? previous : {left, top});
    };
    place();
    const observer = new ResizeObserver(place);
    if (panel.current) observer.observe(panel.current);
    return () => observer.disconnect();
  }, [pointer.x, pointer.y]);

  useEffect(() => {
    const unregister = registerDismiss(() => {onClose(); return true;});
    const outside = (event: Event) => {
      if (!panel.current?.contains(event.target as Node)) onClose();
    };
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("scroll", outside, true);
    window.addEventListener("resize", onClose);
    return () => {
      unregister();
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("scroll", outside, true);
      window.removeEventListener("resize", onClose);
    };
  }, [onClose]);

  return createPortal(
    <div ref={panel} style={position} data-page-comment-popover data-pinned={pointer.pinned}
      role={pointer.pinned ? "dialog" : "region"} aria-label={pointer.pinned ? "Inline comment thread" : "Inline comment preview"}
      onMouseEnter={onKeep} onMouseLeave={onLeave}
      className="fixed z-[60] max-h-[min(26rem,calc(100dvh-1rem))] w-80 max-w-[calc(100vw-1rem)] overflow-y-auto rounded-lg border border-strong bg-overlay p-3 shadow-pop">
      <div className="mb-2 flex items-center justify-between gap-2">
        {pointer.pinned ? <h2 className="text-xs font-semibold text-heading">Inline comment</h2> :
          <button type="button" onClick={onPin} className="text-xs font-semibold text-heading hover:underline">Open thread</button>}
        <button type="button" aria-label="Close inline comment" onClick={onClose}
          className="rounded p-1 text-fg-muted hover:bg-hover focus-visible:outline-2 focus-visible:outline-focus"><X size={14} aria-hidden /></button>
      </div>
      {children}
    </div>, document.body,
  );
}
