import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileSearch, Sparkles, X } from "lucide-react";
import { aiErrorText } from "../../lib/ai";
import { api } from "../../lib/api";
import { ApiPath, apiItemAiSummarizePath } from "../../lib/constants";
import { Markdown } from "../../lib/markdown";
import { aiStatusQuery, similarItemsQuery, similarToTextQuery } from "../../lib/queries";
import { streamSse } from "../../lib/sse";
import { AiBuiltinEditorAction, AiFeature, type AiSummary } from "../../lib/types";
import { SimilarCandidatesList } from "../items/AiSection";
import { useOpenAiResults, type SimilarSeed } from "../items/ai-results";
import { useEditorAi, type AiRun } from "./ai";
import { AiActionPicker } from "./AiActionPicker";

const PANEL_WIDTH = 320;

export type { SimilarSeed };

interface AiReadMenuProps {
  /** The markdown this menu operates on (comment body / description / page). */
  text: string;
  similar?: SimilarSeed;
  /** Summarize the whole ISSUE (description + comments + history + worklogs
   * where the project logs time) via POST /items/{id}/ai/summarize, instead of
   * just this text — set on the description's menu. */
  summarizeItemId?: string;
  /** Present when the actor can rewrite this text — the pick opens the editor
   * with the transform streaming in as a reviewable diff. Leave out where the
   * actor has no write access: the menu then only offers query actions. */
  onTransform?: (run: AiRun) => void;
  /** Accessible name for the trigger button ("AI actions for this comment"). */
  label: string;
  className?: string;
}

type View = "menu" | "similar" | "summary";

/**
 * The read-mode AI menu (spec 103 follow-up): a sparkle button on RENDERED
 * content — no edit mode, no selection needed. Query actions (Find similar,
 * Summarize) answer right in the popover without touching the text; transform
 * actions and the freeform prompt hand off to the editor via `onTransform`.
 * Renders nothing when no gate lets any entry through.
 */
export function AiReadMenu({
  text,
  similar,
  summarizeItemId,
  onTransform,
  label,
  className = "",
}: AiReadMenuProps) {
  const status = useQuery(aiStatusQuery);
  const editorAi = useEditorAi();
  // On the issue page, query answers open in the reading-area results pane
  // (the dead-space fix); elsewhere (pages pages) they answer in this popover.
  const openResults = useOpenAiResults();
  const [anchor, setAnchor] = useState<{ left: number; top: number } | null>(null);
  const [view, setView] = useState<View>("menu");
  const [summary, setSummary] = useState("");
  const [summaryState, setSummaryState] = useState<"streaming" | "done" | "error">("done");
  const [summaryError, setSummaryError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Issue-level summarize (spec 46 endpoint) — used instead of the text
  // stream when the menu speaks for the whole issue (the description).
  const itemSummary = useMutation({
    mutationFn: () => api.post<AiSummary>(apiItemAiSummarizePath(summarizeItemId ?? "")),
  });

  const aiEnabled = status.data?.enabled === true;
  const itemSummarizeOn =
    summarizeItemId !== undefined && status.data?.features?.[AiFeature.summarize] === true;
  const summarizeAction =
    summarizeItemId !== undefined
      ? undefined // whole-issue menus never fall back to text-only summarize
      : editorAi?.actions.find((action) => action.id === AiBuiltinEditorAction.summarize);
  const canQuery =
    aiEnabled && (similar !== undefined || summarizeAction !== undefined || itemSummarizeOn);
  const canTransform = editorAi !== null && onTransform !== undefined;

  const itemSeed = similar && "itemId" in similar ? similar : undefined;
  const textSeed = similar && "seedKey" in similar ? similar : undefined;
  const itemSimilar = useQuery({
    ...similarItemsQuery(itemSeed?.itemId ?? ""),
    enabled: anchor !== null && view === "similar" && itemSeed !== undefined,
  });
  const textSimilar = useQuery({
    ...similarToTextQuery(textSeed?.seedKey ?? "", text, textSeed?.excludeItemId),
    enabled: anchor !== null && view === "similar" && textSeed !== undefined,
  });
  const similarResult = itemSeed ? itemSimilar : textSimilar;

  // Abort a mid-flight summary stream when the menu closes or unmounts.
  useEffect(() => () => abortRef.current?.abort(), []);
  const close = () => {
    abortRef.current?.abort();
    setAnchor(null);
    setView("menu");
  };

  if (text.trim() === "" || (!canQuery && !canTransform)) return null;

  const open = () => {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    setView("menu");
    setAnchor({
      left: Math.min(rect.left, window.innerWidth - PANEL_WIDTH - 8),
      top: rect.bottom + 4,
    });
  };

  const startSummary = async () => {
    setView("summary");
    setSummary("");
    setSummaryState("streaming");
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const frames = streamSse(
        ApiPath.aiEditorStream,
        { action_id: AiBuiltinEditorAction.summarize, document: text, selection: "" },
        controller.signal,
      );
      for await (const chunk of frames) {
        setSummary((current) => current + chunk);
      }
      setSummaryState("done");
    } catch (error) {
      if (controller.signal.aborted) return;
      setSummaryError(aiErrorText(error));
      setSummaryState("error");
    }
  };

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => (anchor ? close() : open())}
        aria-label={label}
        title={label}
        aria-expanded={anchor !== null}
        className={
          "rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer " + className
        }
      >
        <Sparkles size={12} aria-hidden />
      </button>
      {anchor &&
        createPortal(
          <>
            <div className="fixed inset-0 z-[59]" onMouseDown={close} />
            <div
              style={{ position: "fixed", left: anchor.left, top: anchor.top, width: PANEL_WIDTH }}
              className="z-[60] rounded-md border border-strong bg-surface p-1.5 shadow-pop animate-menu-in"
            >
              {view === "menu" ? (
                <div className="flex flex-col gap-1">
                  {canQuery && (
                    <ul className="flex flex-col">
                      {similar && (
                        <MenuEntry
                          icon={<FileSearch size={12} aria-hidden />}
                          label="Find similar issues"
                          onClick={() => {
                            if (openResults) {
                              openResults({ kind: "similar", seed: similar, text });
                              close();
                            } else setView("similar");
                          }}
                        />
                      )}
                      {itemSummarizeOn && (
                        <MenuEntry
                          icon={<Sparkles size={12} aria-hidden />}
                          label="Summarize issue"
                          onClick={() => {
                            if (openResults && summarizeItemId) {
                              openResults({ kind: "item-summary", itemId: summarizeItemId });
                              close();
                              return;
                            }
                            setView("summary");
                            itemSummary.mutate();
                          }}
                        />
                      )}
                      {summarizeAction && (
                        <MenuEntry
                          icon={<Sparkles size={12} aria-hidden />}
                          label={summarizeAction.label}
                          onClick={() => {
                            if (openResults) {
                              openResults({ kind: "text-summary", text });
                              close();
                            } else void startSummary();
                          }}
                        />
                      )}
                    </ul>
                  )}
                  {canQuery && canTransform && <hr className="border-subtle" />}
                  {canTransform && editorAi && (
                    <>
                      <p className="px-2 pt-0.5 text-[10px] font-semibold uppercase tracking-wide text-fg-faint">
                        Edit with AI
                      </p>
                      <AiActionPicker
                        actions={editorAi.actions}
                        onPick={(run) => {
                          close();
                          onTransform?.(run);
                        }}
                      />
                    </>
                  )}
                </div>
              ) : (
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between px-1">
                    <button
                      type="button"
                      onClick={() => {
                        abortRef.current?.abort();
                        setView("menu");
                      }}
                      className="flex items-center gap-1 rounded px-1 py-0.5 text-[11px] text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
                    >
                      <ArrowLeft size={11} aria-hidden />
                      {view === "similar" ? "Similar issues" : "Summary"}
                    </button>
                    <button
                      type="button"
                      onClick={close}
                      aria-label="Close"
                      className="rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer"
                    >
                      <X size={12} aria-hidden />
                    </button>
                  </div>
                  <div className="max-h-72 overflow-y-auto px-1 pb-1">
                    {view === "similar" ? (
                      similarResult.isPending ? (
                        <p className="text-xs text-fg-muted">Looking for similar issues…</p>
                      ) : similarResult.isError ? (
                        <p className="text-xs text-red-400">{aiErrorText(similarResult.error)}</p>
                      ) : (similarResult.data?.candidates.length ?? 0) === 0 ? (
                        <p className="text-xs text-fg-faint">No similar issues found.</p>
                      ) : (
                        <SimilarCandidatesList
                          candidates={similarResult.data?.candidates ?? []}
                          onOpen={close}
                        />
                      )
                    ) : summarizeItemId !== undefined ? (
                      itemSummary.isPending ? (
                        <p className="text-xs text-fg-muted">Reading the issue…</p>
                      ) : itemSummary.isError ? (
                        <p className="text-xs text-red-400">{aiErrorText(itemSummary.error)}</p>
                      ) : (
                        <Markdown text={itemSummary.data?.summary ?? ""} />
                      )
                    ) : summaryState === "error" ? (
                      <p className="text-xs text-red-400">{summaryError}</p>
                    ) : summary === "" ? (
                      <p className="text-xs text-fg-muted">Reading…</p>
                    ) : (
                      <Markdown text={summary} />
                    )}
                  </div>
                </div>
              )}
            </div>
          </>,
          document.body,
        )}
    </>
  );
}

function MenuEntry({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs text-fg hover:bg-elevated cursor-pointer"
      >
        <span className="shrink-0 text-fg-muted">{icon}</span>
        {label}
      </button>
    </li>
  );
}
