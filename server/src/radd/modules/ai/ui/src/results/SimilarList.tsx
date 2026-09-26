import { IssueSuggestion } from "@radd/plugin-sdk";
import type { SimilarCandidate } from "../types";

/**
 * Scored candidates — the reading pane's, the read menu's and the submission form's. The row is
 * the host's `IssueSuggestion` (a peek-aware link, so a half-typed form or the issue being read
 * survives the detour, and a preview on a resting pointer, RADD-924); the score and the reason are
 * this plugin's. `onOpen` lets a hosting popover close itself when a row consumed the click.
 */
export function SimilarCandidatesList({
  candidates,
  onOpen,
  mergeSourceId,
}: {
  candidates: SimilarCandidate[];
  onOpen?: () => void;
  /** When set, each row offers "merge into this" for the item whose panel we are in — the
   * RADD-1090 action on the finding (the seed is the DUPLICATE). */
  mergeSourceId?: string;
}) {
  return (
    <ul className="flex flex-col gap-1.5" data-ai-similar-list>
      {candidates.map((candidate) => (
        <IssueSuggestion
          key={candidate.item_key}
          itemKey={candidate.item_key}
          title={candidate.title}
          badge={
            <span className="shrink-0 rounded-full bg-accent/15 px-1.5 py-0.5 text-[11px] font-medium text-accent-text">
              {Math.round(candidate.score * 100)}%
            </span>
          }
          note={candidate.reason || undefined}
          mergeFrom={mergeSourceId}
          onOpen={onOpen}
        />
      ))}
    </ul>
  );
}
