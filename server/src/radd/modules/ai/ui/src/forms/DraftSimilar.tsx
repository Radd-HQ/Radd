import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { FileSearch } from "lucide-react";
import { api, useDebounced, type ItemDraftAssistProps } from "@radd/plugin-sdk";
import { useAiStatus } from "../queries";
import { SimilarCandidatesList } from "../results/SimilarList";
import { AiEndpoint } from "../transport";
import type { SimilarResponse } from "../types";

/** /ai/similar caps its seed at 20k server-side; a draft embeds fine well before that, and a
 * shorter seed keeps every probe light. */
const SIMILAR_SEED_MAX_CHARS = 8000;
/** A seed shorter than this finds noise. */
const SIMILAR_MIN_SEED_CHARS = 3;
/** The draft settles for this long before a probe. */
const SIMILAR_DEBOUNCE_MS = 800;

/**
 * "Similar issues" beside an issue being written — this plugin's `item.draft.assist` (spec 106,
 * RADD-1395): the /ai/similar semantic-first lookup (vector neighbours when embeddings are up, FTS
 * only as the fallback) seeded with the WHOLE draft, so it keeps improving as the description
 * grows, and surfacing OPEN duplicates the host's deflection deliberately hides. Renders nothing
 * until something matches; issues another section already shows (`exclude`) are not repeated.
 */
export function AiDraftSimilar({ title, description, projectId, exclude }: ItemDraftAssistProps) {
  const status = useAiStatus();
  const seed = `${title}\n\n${description}`.trim().slice(0, SIMILAR_SEED_MAX_CHARS);
  const debouncedSeed = useDebounced(seed, SIMILAR_DEBOUNCE_MS);
  const similar = useQuery({
    // The debounced draft IS the key — unlike the read menu's stable seedKey, a form draft must
    // refetch as it grows (keepPreviousData smooths it).
    queryKey: ["ai", "form-similar", projectId, debouncedSeed],
    queryFn: ({ signal }) =>
      api.post<SimilarResponse>(AiEndpoint.similar, { text: debouncedSeed, exclude_item_id: null }, { signal }),
    // Status error/pending/disabled all mean "don't ask" (the spec 46 gate).
    enabled: Boolean(status.data?.enabled) && debouncedSeed.length >= SIMILAR_MIN_SEED_CHARS,
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 30_000,
  });
  const excluded = new Set(exclude);
  const candidates = (similar.data?.candidates ?? []).filter((candidate) => !excluded.has(candidate.item_key));
  // Gate on the LIVE title too — kept-previous data must not outlive a cleared draft.
  if (title.trim().length < SIMILAR_MIN_SEED_CHARS || candidates.length === 0) return null;
  return (
    <section className="flex flex-col gap-1" data-ai-draft-similar>
      <h3 className="flex items-center gap-1.5 text-[11px] font-medium text-fg-secondary">
        <FileSearch size={12} aria-hidden />
        Similar issues
      </h3>
      <SimilarCandidatesList candidates={candidates} />
    </section>
  );
}
