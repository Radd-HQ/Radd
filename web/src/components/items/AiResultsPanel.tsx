import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { FileSearch, Sparkles, X } from "lucide-react";
import { aiErrorText } from "../../lib/ai";
import { api } from "../../lib/api";
import {
  ApiPath,
  apiItemAiSimilarReasonsPath,
  apiItemAiSummarizePath,
  apiItemAiSummarizeStreamPath,
} from "../../lib/constants";
import { Markdown } from "../../lib/markdown";
import { aiStatusQuery, similarItemsQuery, similarToTextQuery } from "../../lib/queries";
import { streamSse, streamSseJson } from "../../lib/sse";
import {
  AiBuiltinEditorAction,
  AiFeature,
  type AiSummary,
  type SimilarReason,
} from "../../lib/types";
import { SimilarCandidatesList } from "./AiSection";
import type { AiResultRequest } from "./ai-results";

interface AiResultsPanelProps {
  request: AiResultRequest;
  /** Bumped per open — re-runs the summarize even for the same request. */
  runId: number;
  onClose: () => void;
  className?: string;
}

/**
 * The AI results pane on the issue page (the dead-space fix): summarize /
 * find-similar answers land HERE — beside the reading column where there is
 * room — rather than in the w-72 rail card or a 320px popover. Transient by
 * design: nothing is stored, closing it discards the run.
 */
export function AiResultsPanel({ request, runId, onClose, className = "" }: AiResultsPanelProps) {
  const status = useQuery(aiStatusQuery);
  // Wait for the flags before choosing one-shot vs streamed — undefined means
  // "don't start anything yet", so a run never fires twice.
  const streamOn = status.data ? status.data.stream_responses : undefined;
  const reasonsOn =
    status.data ? (status.data.features[AiFeature.similarRerank] ?? false) : undefined;

  const similar = request.kind === "similar" ? request : null;
  const itemSeed = similar && "itemId" in similar.seed ? similar.seed : null;
  const textSeed = similar && "seedKey" in similar.seed ? similar.seed : null;

  const itemSimilar = useQuery({
    ...similarItemsQuery(itemSeed?.itemId ?? ""),
    enabled: itemSeed !== null,
  });
  const textSimilar = useQuery({
    ...similarToTextQuery(textSeed?.seedKey ?? "", similar?.text ?? "", textSeed?.excludeItemId),
    enabled: textSeed !== null,
  });
  const similarResult = itemSeed ? itemSimilar : textSimilar;

  // LLM reasoning hydrates the DISPLAYED candidates over SSE (the rerank
  // feature + streaming on): rows render instantly from the fused pools, the
  // chat-model round trip never blocks them.
  const [reasons, setReasons] = useState<Record<string, SimilarReason>>({});
  const [reasoning, setReasoning] = useState(false);
  const reasonsAbortRef = useRef<AbortController | null>(null);
  const itemCandidates = itemSeed ? itemSimilar.data?.candidates : undefined;
  const itemSeedId = itemSeed?.itemId;
  const alreadyReranked = itemSimilar.data?.reranked ?? false;
  useEffect(() => {
    reasonsAbortRef.current?.abort();
    setReasons({});
    setReasoning(false);
    if (
      !itemSeedId ||
      !itemCandidates?.length ||
      alreadyReranked || // streaming off: the list arrived reranked in one go
      !reasonsOn ||
      !streamOn
    ) {
      return;
    }
    const controller = new AbortController();
    reasonsAbortRef.current = controller;
    setReasoning(true);
    void (async () => {
      try {
        const frames = streamSseJson(
          apiItemAiSimilarReasonsPath(itemSeedId),
          { keys: itemCandidates.map((candidate) => candidate.item_key) },
          controller.signal,
        );
        for await (const frame of frames) {
          if (typeof frame.key !== "string" || typeof frame.score !== "number") continue;
          const reason = typeof frame.reason === "string" ? frame.reason : null;
          const entry: SimilarReason = { key: frame.key, score: frame.score, reason };
          setReasons((current) => ({ ...current, [entry.key]: entry }));
        }
      } catch {
        // Reasons are an enhancement — the base candidates stand on their own.
      } finally {
        if (!controller.signal.aborted) setReasoning(false);
      }
    })();
    return () => controller.abort();
  }, [itemSeedId, itemCandidates, alreadyReranked, reasonsOn, streamOn, runId]);

  // Whole-issue digest, ONE GO (the Stream-AI-responses setting off).
  const itemSummary = useMutation({
    mutationFn: (itemId: string) => api.post<AiSummary>(apiItemAiSummarizePath(itemId)),
  });
  const { mutate: runItemSummary } = itemSummary;
  useEffect(() => {
    if (request.kind === "item-summary" && streamOn === false) runItemSummary(request.itemId);
  }, [request, runId, streamOn, runItemSummary]);

  // Streamed summaries: the whole-issue digest (streaming on) and the text
  // summarize (a comment — always streamed via the editor endpoint).
  const [stream, setStream] = useState("");
  const [streamState, setStreamState] = useState<"streaming" | "done" | "error">("done");
  const [streamError, setStreamError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => {
    const itemDigest = request.kind === "item-summary" && streamOn === true;
    if (request.kind !== "text-summary" && !itemDigest) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStream("");
    setStreamState("streaming");
    void (async () => {
      try {
        const frames = itemDigest
          ? streamSse(apiItemAiSummarizeStreamPath(request.itemId), {}, controller.signal)
          : streamSse(
              ApiPath.aiEditorStream,
              {
                action_id: AiBuiltinEditorAction.summarize,
                document: request.kind === "text-summary" ? request.text : "",
                selection: "",
              },
              controller.signal,
            );
        for await (const chunk of frames) setStream((current) => current + chunk);
        setStreamState("done");
      } catch (error) {
        if (controller.signal.aborted) return;
        setStreamError(aiErrorText(error));
        setStreamState("error");
      }
    })();
    return () => controller.abort();
  }, [request, runId, streamOn]);

  const title = request.kind === "similar" ? "Similar issues" : "Summary";
  const Icon = request.kind === "similar" ? FileSearch : Sparkles;

  return (
    <aside
      aria-label={`AI results — ${title}`}
      className={`flex flex-col rounded-xl border border-subtle bg-surface shadow-lift ${className}`}
    >
      <div className="flex shrink-0 items-center gap-1.5 border-b border-subtle px-3 py-2">
        <Icon size={12} className="text-fg-muted" aria-hidden />
        <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{title}</h3>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close AI results"
          className="ml-auto rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer"
        >
          <X size={13} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {request.kind === "similar" ? (
          similarResult.isPending ? (
            <p className="text-xs text-fg-muted">Looking for similar issues…</p>
          ) : similarResult.isError ? (
            <p className="text-xs text-red-400">{aiErrorText(similarResult.error)}</p>
          ) : (similarResult.data?.candidates.length ?? 0) === 0 ? (
            <p className="text-xs text-fg-faint">No similar issues found.</p>
          ) : (
            <>
              <SimilarCandidatesList
                // Reasons/scores hydrate IN PLACE — rows must never reshuffle
                // under the pointer, so the fused pool order stands.
                candidates={(similarResult.data?.candidates ?? []).map((candidate) => {
                  const streamed = reasons[candidate.item_key];
                  if (!streamed) return candidate;
                  return {
                    ...candidate,
                    score: streamed.score,
                    reason: streamed.reason ?? candidate.reason,
                  };
                })}
              />
              {reasoning && (
                <p className="mt-2 flex items-center gap-1.5 text-[11px] text-fg-faint">
                  <Sparkles size={11} aria-hidden className="animate-pulse" />
                  Reasoning about matches…
                </p>
              )}
            </>
          )
        ) : request.kind === "item-summary" && streamOn === false ? (
          itemSummary.isPending || itemSummary.isIdle ? (
            <p className="text-xs text-fg-muted">Reading the issue…</p>
          ) : itemSummary.isError ? (
            <p className="text-xs text-red-400">{aiErrorText(itemSummary.error)}</p>
          ) : (
            <Markdown text={itemSummary.data?.summary ?? ""} />
          )
        ) : streamState === "error" ? (
          <p className="text-xs text-red-400">{streamError}</p>
        ) : stream === "" ? (
          <p className="text-xs text-fg-muted">Reading…</p>
        ) : (
          <Markdown text={stream} />
        )}
      </div>
    </aside>
  );
}
