import { useCallback, useEffect, useRef, useState } from "react";

export interface CommentHit { id: string; range: Range }
export interface CommentPointer { id: string; x: number; y: number; pinned: boolean }

/** Hit test cached annotation ranges, never re-walk the document on mousemove. */
export function useCommentPointer(
  bodyRef: React.RefObject<HTMLElement | null>,
  hits: React.RefObject<CommentHit[]>,
  editing: boolean,
  onOpen: (id: string) => void,
) {
  const [pointer, setPointer] = useState<CommentPointer | null>(null);
  const current = useRef(pointer);
  current.current = pointer;
  const onOpenRef = useRef(onOpen);
  onOpenRef.current = onOpen;
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const keep = useCallback(() => clearTimeout(timer.current), []);
  const close = useCallback(() => { keep(); setPointer(null); }, [keep]);
  const leave = useCallback(() => {
    keep();
    timer.current = setTimeout(() => setPointer(value => value?.pinned ? value : null), 220);
  }, [keep]);
  const pin = useCallback(() => {
    keep();
    const value = current.current;
    if (value) { setPointer({...value, pinned: true}); onOpenRef.current(value.id); }
  }, [keep]);

  useEffect(() => {
    const host = bodyRef.current;
    if (!host) return;
    close();
    let frame = 0;
    const hit = (event: MouseEvent) => {
      if (event.buttons || !window.getSelection()?.isCollapsed) return;
      if ((event.target as Element).closest("a,button,input,textarea,select")) return;
      return hits.current.find(({range}) => range.startContainer.isConnected &&
        Array.from(range.getClientRects()).some(rect => rect.width > 0 && rect.height > 0 &&
          event.clientX >= rect.left && event.clientX <= rect.right &&
          event.clientY >= rect.top && event.clientY <= rect.bottom));
    };
    const move = (event: MouseEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (current.current?.pinned) return;
        const target = hit(event);
        if (!target) { leave(); return; }
        keep();
        // Stay still while crossing the same passage, so the card is reachable.
        setPointer(value => value?.id === target.id ? value : {
          id: target.id, x: event.clientX, y: event.clientY, pinned: false,
        });
      });
    };
    const click = (event: MouseEvent) => {
      const target = hit(event);
      if (!target) return;
      keep();
      setPointer({id: target.id, x: event.clientX, y: event.clientY, pinned: true});
      onOpenRef.current(target.id);
    };
    const down = () => { if (!current.current?.pinned) close(); };
    host.addEventListener("mousemove", move);
    host.addEventListener("mouseleave", leave);
    host.addEventListener("mousedown", down);
    host.addEventListener("click", click);
    return () => {
      cancelAnimationFrame(frame);
      keep();
      host.removeEventListener("mousemove", move);
      host.removeEventListener("mouseleave", leave);
      host.removeEventListener("mousedown", down);
      host.removeEventListener("click", click);
    };
  }, [bodyRef, hits, editing, close, keep, leave]);

  return {pointer, close, keep, leave, pin};
}
