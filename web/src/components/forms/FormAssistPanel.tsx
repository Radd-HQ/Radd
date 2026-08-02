import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { FileSearch } from "lucide-react";
import { api } from "../../lib/api";
import {
  ApiPath,
  DEFLECT_DEBOUNCE_MS,
  DEFLECT_MIN_QUERY_CHARS,
  FORM_SIMILAR_DEBOUNCE_MS,
} from "../../lib/constants";
import { useDebounced } from "../../lib/hooks";
import { aiStatusQuery, deflectQuery } from "../../lib/queries";
import type { SimilarResponse } from "../../lib/types";
import { SimilarCandidatesList } from "../items/AiSection";
import { DeflectDocsSection, DeflectItemsSection } from "../items/DeflectionPanel";

interface FormAssistPanelProps {
  /** The draft title — seeds deflection alone (FTS wants short, dense text). */
  title: string;
  /** The draft description — joins the title as the similar-issues seed. */
  description: string;
  projectId: string;
  className?: string;
}

/** /ai/similar caps its seed at 20k server-side; a draft embeds fine well
 * before that, and a shorter seed keeps every probe light. */
const SIMILAR_SEED_MAX_CHARS = 8000;

/**
 * Submit-time assist for the AUTHED form pages (spec 106): KB deflection
 * (spec 66) plus "Similar issues" — the /ai/similar semantic-first lookup
 * (vector neighbors when embeddings are up, FTS only as the fallback) seeded
 * with the WHOLE draft, so it keeps improving as the description grows, and
 * surfacing OPEN duplicates deflection deliberately hides. Renders nothing until the title is long enough and something
 * matches; every link opens a new tab so the half-typed form survives.
 * Mounted twice per page (inline on narrow, an aside when the container is
 * wide) — the queries dedupe on their keys, so the second mount is free.
 */
export function FormAssistPanel({
  title,
  description,
  projectId,
  className = "",
}: FormAssistPanelProps) {
  const debouncedTitle = useDebounced(title, DEFLECT_DEBOUNCE_MS);
  const deflect = useQuery(deflectQuery(debouncedTitle, projectId));

  const status = useQuery(aiStatusQuery);
  const seed = `${title}\n\n${description}`.trim().slice(0, SIMILAR_SEED_MAX_CHARS);
  const debouncedSeed = useDebounced(seed, FORM_SIMILAR_DEBOUNCE_MS);
  const similar = useQuery({
    // The debounced draft IS the key — unlike the read-menu's stable seedKey,
    // a form draft must refetch as it grows (keepPreviousData smooths it).
    queryKey: ["form-similar", projectId, debouncedSeed],
    queryFn: () =>
      api.post<SimilarResponse>(ApiPath.aiSimilar, {
        text: debouncedSeed,
        exclude_item_id: null,
      }),
    // Status error/pending/disabled all mean "don't ask" (the spec 46 gate).
    enabled:
      Boolean(status.data?.enabled) && debouncedSeed.length >= DEFLECT_MIN_QUERY_CHARS,
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 30_000,
  });

  const docs = deflect.data?.docs ?? [];
  const resolved = deflect.data?.items ?? [];
  // Deflection already shows resolved twins — don't repeat them as "similar".
  const resolvedKeys = new Set(resolved.map((item) => item.key));
  const candidates = (similar.data?.candidates ?? []).filter(
    (candidate) => !resolvedKeys.has(candidate.item_key),
  );

  // Gate on the LIVE title too — kept-previous data must not outlive a cleared draft.
  if (title.trim().length < DEFLECT_MIN_QUERY_CHARS) return null;
  if (docs.length === 0 && resolved.length === 0 && candidates.length === 0) return null;

  return (
    <div
      className={
        "flex flex-col gap-2.5 rounded-md border border-subtle bg-surface/40 p-2.5 " + className
      }
    >
      <DeflectDocsSection docs={docs} />
      <DeflectItemsSection items={resolved} />
      {candidates.length > 0 && (
        <section className="flex flex-col gap-1">
          <h3 className="flex items-center gap-1.5 text-[11px] font-medium text-fg-secondary">
            <FileSearch size={12} aria-hidden />
            Similar issues
          </h3>
          <SimilarCandidatesList candidates={candidates} />
        </section>
      )}
    </div>
  );
}
