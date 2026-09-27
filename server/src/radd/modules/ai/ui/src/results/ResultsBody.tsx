import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { api, ErrorText, Markdown } from "@radd/plugin-sdk";
import { useAiStatus, similarItemsQuery, similarToTextQuery } from "../queries";
import { streamSse, streamSseJson } from "../sse";
import {
  AiEndpoint,
  aiErrorText,
  itemSimilarReasonsPath,
  itemSummarizePath,
  itemSummarizeStreamPath,
} from "../transport";
import {
  AiBuiltinEditorAction,
  AiFeature,
  type AiResultRequest,
  type AiSummary,
  type SimilarReason,
} from "../types";
import { SimilarCandidatesList } from "./SimilarList";

/** An AI answer, in the reading pane (the frame is the host's) or the read menu's popover.
 *  Transient: nothing is stored, and closing it discards the run. `onOpen` lets a popover close
 *  when a similar-issue row consumed the click. */
export function AiResultsBody({ request, onOpen }: { request: AiResultRequest; onOpen?: () => void }) {
  const status = useAiStatus();
  // Wait for the flags before choosing one-shot vs streamed — undefined means "don't start
  // anything yet", so a run never fires twice.
  const streamOn = status.data ? status.data.stream_responses : undefined;
  const reasonsOn = status.data ? (status.data.features[AiFeature.similarRerank] ?? false) : undefined;

  const similar = request.kind === "similar" ? request : null;
  const itemSeed = similar && "itemId" in similar.seed ? similar.seed : null;
  const textSeed = similar && "seedKey" in similar.seed ? similar.seed : null;

  const itemSimilar = useQuery({ ...similarItemsQuery(itemSeed?.itemId ?? ""), enabled: itemSeed !== null });
  const textSimilar = useQuery({
    ...similarToTextQuery(textSeed?.seedKey ?? "", similar?.text ?? "", textSeed?.excludeItemId),
    enabled: textSeed !== null,
  });
  const similarResult = itemSeed ? itemSimilar : textSimilar;

  // Reasoning hydrates the DISPLAYED candidates over SSE (the rerank feature + streaming on): rows
  // render instantly from the fused pools, the chat-model round trip never blocks them.
  const [reasons, setReasons] = useState<Record<string, SimilarReason>>({});
  const [reasoning, setReasoning] = useState(false);
  const itemCandidates = itemSeed ? itemSimilar.data?.candidates : undefined;
  const itemSeedId = itemSeed?.itemId;
  const alreadyReranked = itemSimilar.data?.reranked ?? false;
  useEffect(() => {
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
    setReasoning(true);
    void (async () => {
      try {
        const frames = streamSseJson(
          itemSimilarReasonsPath(itemSeedId),
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
  }, [itemSeedId, itemCandidates, alreadyReranked, reasonsOn, streamOn]);

  // Whole-issue digest, ONE GO (the Stream-AI-responses setting off).
  const itemSummary = useMutation({
    mutationFn: (itemId: string) => api.post<AiSummary>(itemSummarizePath(itemId)),
  });
  const { mutate: runItemSummary } = itemSummary;
  useEffect(() => {
    if (request.kind === "item-summary" && streamOn === false) runItemSummary(request.itemId);
  }, [request, streamOn, runItemSummary]);

  // Streamed summaries: the whole-issue digest (streaming on) and the text summarize (a comment or
  // a page — always streamed via the editor endpoint).
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
          ? streamSse(itemSummarizeStreamPath(request.itemId), {}, controller.signal)
          : streamSse(
              AiEndpoint.editorStream,
              {
                action_id: AiBuiltinEditorAction.summarize,
                document: request.kind === "text-summary" ? request.text : "",
                selection: "",
                // RADD-1275: a page's images.
                ...(request.kind === "text-summary" && request.imagesOf ? { images_of: request.imagesOf } : {}),
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
  }, [request, streamOn]);

  if (request.kind === "similar") {
    if (similarResult.isPending) return <p className="text-xs text-fg-muted">Looking for similar issues…</p>;
    if (similarResult.isError) return <p className="text-xs text-status-danger-ink">{aiErrorText(similarResult.error)}</p>;
    if ((similarResult.data?.candidates.length ?? 0) === 0) return <p className="text-xs text-fg-faint">No similar issues found.</p>;
    return (
      <>
        <SimilarCandidatesList
          mergeSourceId={itemSeed?.itemId}
          onOpen={onOpen}
          // Reasons/scores hydrate IN PLACE — rows must never reshuffle under the pointer, so the
          // fused pool order stands.
          candidates={(similarResult.data?.candidates ?? []).map((candidate) => {
            const streamed = reasons[candidate.item_key];
            if (!streamed) return candidate;
            return { ...candidate, score: streamed.score, reason: streamed.reason ?? candidate.reason };
          })}
        />
        {reasoning && (
          <p className="mt-2 flex items-center gap-1.5 text-[11px] text-fg-faint">
            <Sparkles size={11} aria-hidden className="animate-pulse" />
            Reasoning about matches…
          </p>
        )}
      </>
    );
  }
  if (request.kind === "item-summary" && streamOn === false) {
    if (itemSummary.isPending || itemSummary.isIdle) return <p className="text-xs text-fg-muted">Reading the issue…</p>;
    if (itemSummary.isError) return <p className="text-xs text-status-danger-ink">{aiErrorText(itemSummary.error)}</p>;
    return <Markdown text={itemSummary.data?.summary ?? ""} />;
  }
  if (streamState === "error") return <ErrorText error={streamError} />;
  if (stream === "") return <p className="text-xs text-fg-muted">Reading…</p>;
  return <Markdown text={stream} />;
}
