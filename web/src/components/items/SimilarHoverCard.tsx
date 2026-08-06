/**
 * "Is this one actually relevant?" — without leaving what you were doing (RADD-924).
 *
 * The similar-issues box gives a key, a title and a score. That is enough to
 * decide something is obviously the same bug and nowhere near enough to decide
 * it is NOT — so the only way to check was to open it, which on the submission
 * form means abandoning a half-typed draft, and on an issue you are reading
 * means losing your place. People stopped checking, which makes a duplicate
 * detector that nobody trusts.
 *
 * So: dwell on a candidate and the issue's own summary and description come to
 * you. Fetched lazily and cached (`itemByKeyQuery`), so sweeping the list costs
 * one request per issue you actually paused on, and the read goes through the
 * ordinary item endpoint — an issue the viewer may not read answers 403 and the
 * card says so rather than leaking a title into a tooltip.
 *
 * Positioning follows `RoadmapHoverCard`: render at the raw anchor, then correct
 * pre-paint once the real height is measurable. Flipping above the row is not
 * cosmetic — this list is often at the BOTTOM of a form, where a card that only
 * ever opens downward is a card nobody can read.
 */
import { useLayoutEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { itemByKeyQuery } from "../../lib/queries";
import { PRIORITY_META } from "../../lib/meta";
import { previewText } from "../../lib/plain-text";
import { AssigneeAvatar, PriorityIcon, StatePill } from "./ItemBadges";

const CARD_WIDTH_PX = 340;
const CARD_GAP_PX = 8;
const CARD_VIEWPORT_MARGIN_PX = 8;

export interface SimilarHoverCardProps {
  itemKey: string;
  /** The hovered row's viewport rect, captured when the dwell timer fired. */
  anchor: { left: number; top: number; bottom: number };
}

export function SimilarHoverCard({ itemKey, anchor }: SimilarHoverCardProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const item = useQuery(itemByKeyQuery(itemKey));

  const [pos, setPos] = useState({ left: anchor.left, top: anchor.bottom + CARD_GAP_PX });
  useLayoutEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    let top = anchor.bottom + CARD_GAP_PX;
    if (top + rect.height > window.innerHeight - CARD_VIEWPORT_MARGIN_PX) {
      top = anchor.top - rect.height - CARD_GAP_PX;
    }
    top = Math.max(
      CARD_VIEWPORT_MARGIN_PX,
      Math.min(top, window.innerHeight - rect.height - CARD_VIEWPORT_MARGIN_PX),
    );
    const left = Math.max(
      CARD_VIEWPORT_MARGIN_PX,
      Math.min(anchor.left, window.innerWidth - rect.width - CARD_VIEWPORT_MARGIN_PX),
    );
    setPos({ left, top });
    // The fetch changes the card's HEIGHT, so the correction has to re-run when
    // it lands — otherwise a card that opened upward while loading overlaps the
    // row it describes the moment the description arrives.
  }, [anchor, item.data, item.isPending]);

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
