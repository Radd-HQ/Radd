/**
 * Hover preview for a suggested issue: dwell on a row and its summary/description arrive (lazy,
 * cached, through the ordinary item endpoint — a 403 says so rather than leaking a title). Positioned
 * like `RoadmapHoverCard`: raw anchor, then corrected pre-paint, flipping above near the viewport bottom.
 */
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAnchoredCardPosition, type CardAnchor } from "../../lib/floating-position";
import { itemByKeyQuery } from "../../lib/queries";
import { PRIORITY_META } from "../../lib/meta";
import { previewText } from "../../lib/plain-text";
import { AssigneeAvatar, PriorityIcon, StatePill } from "./ItemBadges";

/** How long a pointer must rest before the preview opens. Long enough that
 * sweeping a list fetches nothing, short enough that pausing feels answered.
 * Matches the roadmap hover card, so the app has one dwell. */
const HOVER_DWELL_MS = 350;

/** Dwell/anchor/dismiss behaviour shared by every suggested-issue list; spread `handlers` on the row. */
export function useIssuePreview() {
  const rowRef = useRef<HTMLElement | null>(null);
  const dwellRef = useRef<number | null>(null);
  const [anchor, setAnchor] = useState<CardAnchor | null>(null);

  const close = () => {
    if (dwellRef.current !== null) window.clearTimeout(dwellRef.current);
    dwellRef.current = null;
    setAnchor(null);
  };

  const open = () => {
    const rect = rowRef.current?.getBoundingClientRect();
    if (rect) setAnchor({ left: rect.left, top: rect.top, bottom: rect.bottom });
  };

  const dwell = () => {
    if (dwellRef.current !== null) window.clearTimeout(dwellRef.current);
    dwellRef.current = window.setTimeout(open, HOVER_DWELL_MS);
  };

  // Escape closes it, and so does scrolling: the card is `fixed`, so its anchor
  // would otherwise drift away from the row it describes.
  useEffect(() => {
    if (!anchor) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", close, true);
    };
  }, [anchor]);

  // A pending dwell dies with the row — a timer firing after unmount sets state
  // on nothing.
  useEffect(() => close, []);

  return {
    anchor,
    handlers: {
      ref: (node: HTMLElement | null) => {
        rowRef.current = node;
      },
      onMouseEnter: dwell,
      onMouseLeave: close,
      // Keyboard parity: tabbing to the row opens it immediately. A dwell means
      // nothing without a pointer, and this is the only way a keyboard user
      // gets the description at all.
      onFocus: open,
      onBlur: close,
    },
  };
}

const CARD_WIDTH_PX = 340;

interface SimilarHoverCardProps {
  itemKey: string;
  /** The hovered row's viewport rect, captured when the dwell timer fired. */
  anchor: CardAnchor;
}

export function SimilarHoverCard({ itemKey, anchor }: SimilarHoverCardProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const item = useQuery(itemByKeyQuery(itemKey));
  // The fetch changes the card's HEIGHT, so the correction re-runs when it lands —
  // otherwise a card that opened upward while loading overlaps its row.
  const pos = useAnchoredCardPosition(rootRef, anchor, [item.data, item.isPending]);

  const data = item.data;
  const description = data?.description ? previewText(data.description) : "";

  return (
    <div
      ref={rootRef}
      role="tooltip"
      data-similar-hover-card={itemKey}
      style={{ left: pos.left, top: pos.top, width: CARD_WIDTH_PX }}
      className="pointer-events-none fixed z-50 rounded-lg border border-strong bg-surface p-3 shadow-xl shadow-black/40"
    >
      <p className="font-mono text-[11px] text-fg-muted">{itemKey}</p>

      {item.isPending && <p className="mt-1 text-[12px] text-fg-muted">Loading…</p>}

      {item.isError && (
        // Most often a permission refusal. Saying which is better than an empty
        // card that reads as a bug, and better than inventing a preview.
        <p className="mt-1 text-[12px] text-fg-muted">
          You can’t open this issue, so there’s nothing to preview.
        </p>
      )}

      {data && (
        <>
          <p className="mt-0.5 text-[13px] font-medium leading-snug text-heading">{data.title}</p>

          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <StatePill state={data.state} />
            <span className="inline-flex items-center gap-1 text-[11px] text-fg-secondary">
              <PriorityIcon priority={data.priority} size={13} />
              {PRIORITY_META[data.priority].label}
            </span>
            {data.assignee ? (
              <span className="inline-flex items-center gap-1 text-[11px] text-fg-secondary">
                <AssigneeAvatar assignee={data.assignee} />
                {data.assignee.name}
              </span>
            ) : (
              <span className="text-[11px] text-fg-faint">Unassigned</span>
            )}
          </div>

          {description ? (
            <p className="mt-2 whitespace-pre-line text-[12px] leading-relaxed text-fg-secondary">
              {description}
            </p>
          ) : (
            // A stated absence. A blank space here reads as "still loading".
            <p className="mt-2 text-[12px] italic text-fg-faint">No description.</p>
          )}
        </>
      )}
    </div>
  );
}
