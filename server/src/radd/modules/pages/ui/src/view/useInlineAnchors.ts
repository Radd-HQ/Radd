import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import {
  makeAnchor, offsetsForSelection, orderByAnchor, rangeForOffsets, renderedText,
  type AnchorLocation, type CommentRow, type TextAnchor,
} from "@radd/plugin-sdk";
import type { OrphanReason } from "./PageCommentThread";
import type { CommentHit } from "./useCommentPointer";

const HIGHLIGHT = "radd-inline-comment";
const HIGHLIGHT_FOCUS = "radd-inline-comment-focus";

export interface LocatedComment { row: CommentRow; start: number | null; orphaned: OrphanReason | null }

/**
 * Where each inline comment's passage is on the RENDERED page (RADD-726), kept current as the body
 * re-renders, and the selection a reader can comment on (RADD-731).
 *
 * **Highlighting uses the CSS Custom Highlight API**, not wrapped `<mark>` elements. The body is
 * rendered by ProseMirror, which owns that DOM and reconciles it; inserting elements into it
 * invites the editor to fight back or to serialise our markup into the document. `CSS.highlights`
 * paints ranges without touching the tree at all. Where it is unsupported the comments still work
 * — only the tint is missing, which is the right thing to lose.
 */
export function useInlineAnchors({ bodyRef, bodyVersion, editing, inline, focusedId, canComment }: {
  bodyRef: RefObject<HTMLElement | null>;
  bodyVersion: number;
  editing: boolean;
  inline: CommentRow[];
  focusedId: string | null;
  canComment: boolean;
}) {
  const focusedIdRef = useRef(focusedId);
  focusedIdRef.current = focusedId;
  const hits = useRef<CommentHit[]>([]);
  const pendingSelection = useRef<TextAnchor | null>(null);
  const [located, setLocated] = useState<LocatedComment[]>([]);
  const [selectionAt, setSelectionAt] = useState<{ left: number; top: number } | null>(null);
  // Exclude editor toolbars and page controls from the anchor coordinate space.
  const anchorRoot = useCallback(() => {
    const host = bodyRef.current;
    return host?.querySelector<HTMLElement>("[data-page-body]") ?? host?.querySelector<HTMLElement>(".ProseMirror") ?? host;
  }, [bodyRef]);

  // Locate every anchor against the current rendered text, in document order.
  const rescan = useCallback(() => {
    const root = anchorRoot();
    if (!root) return;
    const ordered = orderByAnchor(renderedText(root), inline);
    setLocated(ordered.map(({ row, location }) => ({
      row, start: location?.status === "located" ? location.start : null, orphaned: orphanReason(location),
    })));
    // Cache visible ranges for pointer hit testing as well as highlighting.
    hits.current = [];
    const open: Range[] = [];
    const focused: Range[] = [];
    for (const { row, location } of ordered) {
      if ((row.resolved_at && row.id !== focusedIdRef.current) || location?.status !== "located") continue;
      const range = rangeForOffsets(root, location.start, location.end);
      if (!range) continue;
      if (!row.resolved_at) hits.current.push({ id: row.id, range });
      (row.id === focusedIdRef.current ? focused : open).push(range);
    }
    if (typeof CSS === "undefined" || !("highlights" in CSS)) return;
    CSS.highlights.set(HIGHLIGHT, new Highlight(...open));
    CSS.highlights.set(HIGHLIGHT_FOCUS, new Highlight(...focused));
  }, [anchorRoot, inline, focusedId]);

  useEffect(() => {
    rescan();
    let frame = 0;
    const observer = new MutationObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(rescan);
    });
    if (bodyRef.current) observer.observe(bodyRef.current, { subtree: true, childList: true, characterData: true });
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      if (typeof CSS !== "undefined" && "highlights" in CSS) {
        CSS.highlights.delete(HIGHLIGHT);
        CSS.highlights.delete(HIGHLIGHT_FOCUS);
      }
    };
  }, [rescan, bodyVersion, bodyRef, editing]);

  // RADD-731: select text in the body, comment on it.
  useEffect(() => {
    if (!anchorRoot() || !canComment) return;
    const onUp = () => {
      const root = anchorRoot();
      if (!root) return;
      const offsets = offsetsForSelection(root);
      if (!offsets) {
        setSelectionAt(null);
        return;
      }
      pendingSelection.current = makeAnchor(renderedText(root), offsets.start, offsets.end);
      const rect = window.getSelection()?.getRangeAt(0).getBoundingClientRect();
      if (rect) setSelectionAt({ left: rect.left, top: rect.bottom + 6 });
    };
    document.addEventListener("mouseup", onUp);
    return () => document.removeEventListener("mouseup", onUp);
  }, [anchorRoot, canComment, bodyVersion, editing]);

  return {
    anchorRoot, located, hits, rescan, selectionAt,
    /** Take the pending selection's anchor, dismissing the floating Comment button. */
    takeSelection: () => { setSelectionAt(null); return pendingSelection.current; },
  };
}

/** The rail's word for a location that is not "located" — null when it is. */
function orphanReason(location: AnchorLocation | null): OrphanReason | null {
  if (!location || location.status === "located") return null;
  return location.status === "ambiguous" ? "ambiguous" : "removed";
}
