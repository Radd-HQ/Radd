import { useEffect, useRef, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { FileSearch, Sparkles } from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { useOpenIssueRef } from "../../lib/hooks";
import { aiStatusQuery } from "../../lib/queries";
import type { Item, SimilarCandidate } from "../../lib/types";
import { Button } from "../Button";
import { useOpenAiResults } from "./ai-results";
import { SimilarHoverCard } from "./SimilarHoverCard";

/**
 * "AI" section in the issue rail (spec 46): on-demand summarize +
 * find-similar. The ANSWERS open in the reading area's results pane
 * (AiResultsPanel) — the rail is far too narrow to read a digest in.
 * Renders nothing unless GET /ai/status says enabled — no dead buttons.
 */
export function AiSection({ item }: { item: Item }) {
  const status = useQuery(aiStatusQuery);
  // Provided by the issue detail body — this section renders nowhere else.
  const openResults = useOpenAiResults();

  // Status error/pending/disabled all mean "render nothing" (spec 46 gate).
  if (!status.data?.enabled || !openResults) return null;

  return (
    <section className="rounded-xl border border-subtle bg-surface p-3 shadow-lift">
      <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">
        <Sparkles size={12} aria-hidden />
        AI
      </h3>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => openResults({ kind: "item-summary", itemId: item.id })}
        >
          <Sparkles size={12} aria-hidden />
          Summarize
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() =>
            openResults({ kind: "similar", seed: { itemId: item.id }, text: item.title })
          }
        >
          <FileSearch size={12} aria-hidden />
          Find similar
        </Button>
      </div>
    </section>
  );
}

/** Scored candidates as links — shared with the results pane, read menu, and
 * the form assist panel. Plain clicks open the PEEK (peek-aware via
 * useOpenIssueRef), so a half-typed form or the issue being read survives the
 * detour; `onOpen` lets a hosting popover close itself when a row consumed
 * the click. */
export function SimilarCandidatesList({
  candidates,
  onOpen,
}: {
  candidates: SimilarCandidate[];
  onOpen?: () => void;
}) {
  return (
    <ul className="flex flex-col gap-1.5">
      {candidates.map((candidate) => (
        <SimilarRow key={candidate.item_key} candidate={candidate} onOpen={onOpen} />
      ))}
    </ul>
  );
}

/** How long a pointer must rest before the preview opens. Long enough that
 * sweeping the list fetches nothing, short enough that pausing feels answered.
 * Matches the roadmap hover card, so the app has one dwell. */
const HOVER_DWELL_MS = 350;

/** One scored candidate: key + title as a link, score as a percent chip, and a
 * hover preview so relevance is checkable without opening it (RADD-924). */
function SimilarRow({
  candidate,
  onOpen,
}: {
  candidate: SimilarCandidate;
  onOpen?: () => void;
}) {
  const openRef = useOpenIssueRef();
  const rowRef = useRef<HTMLLIElement>(null);
  const dwellRef = useRef<number | null>(null);
  const [anchor, setAnchor] = useState<{ left: number; top: number; bottom: number } | null>(null);

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

  // Escape closes it, and it closes on scroll because the card is `fixed` — its
  // anchor would otherwise drift away from the row it describes.
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

  // Any pending dwell dies with the row — a timer that fires after unmount sets
  // state on nothing.
  useEffect(() => close, []);

  return (
    <li
      ref={rowRef}
      className="rounded-md border border-subtle bg-surface/50 px-2.5 py-1.5"
      onMouseEnter={dwell}
      onMouseLeave={close}
      // Keyboard parity: tabbing to the link opens it immediately. A dwell makes
      // no sense without a pointer, and the preview is the only way a keyboard
      // user gets the description at all.
      onFocus={open}
      onBlur={close}
    >
      {anchor && <SimilarHoverCard itemKey={candidate.item_key} anchor={anchor} />}
      <div className="flex items-center gap-2">
        <Link
          to={RoutePath.issue}
          params={{ itemKey: candidate.item_key }}
          onClick={(event) => {
            if (openRef(candidate.item_key, event)) onOpen?.();
          }}
          className="min-w-0 flex-1 truncate text-[13px] text-fg hover:underline"
        >
          <span className="mr-1.5 font-mono text-[11px] text-fg-muted">{candidate.item_key}</span>
          {candidate.title}
        </Link>
        <span className="shrink-0 rounded-full bg-accent/15 px-1.5 py-0.5 text-[11px] font-medium text-accent-text">
          {Math.round(candidate.score * 100)}%
        </span>
      </div>
      {candidate.reason && <p className="mt-0.5 text-[11px] text-fg-faint">{candidate.reason}</p>}
    </li>
  );
}
