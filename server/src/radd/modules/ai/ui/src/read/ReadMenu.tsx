import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileSearch, Sparkles, X } from "lucide-react";
import { api, ErrorText, Markdown, type ReadActionProps } from "@radd/plugin-sdk";
import { AiActionPicker } from "../editor/ActionPicker";
import { useEditorAi } from "../editor/gate";
import { aiTransform } from "../editor/transform";
import { useAiStatus, similarItemsQuery, similarToTextQuery } from "../queries";
import { SimilarCandidatesList } from "../results/SimilarList";
import { useOpenAiResults } from "../results/open";
import { streamSse } from "../sse";
import { AiEndpoint, aiErrorText, itemSummarizePath } from "../transport";
import { AiBuiltinEditorAction, AiFeature, type AiSummary, type ImagesOf, type SimilarSeed } from "../types";

const PANEL_WIDTH = 320;

type View = "menu" | "similar" | "summary";

/** What this plugin reads out of a read action's context. The host says what the content IS; the
 * seeds, the whole-issue summary and the images a summary may look at are this plugin's policy. */
function readingOf(context: ReadActionProps["context"]): {
  similar: SimilarSeed;
  summarizeItemId?: string;
  imagesOf?: ImagesOf;
} {
  // An issue's own content is its description: the issue seeds Find similar (its stored vector +
  // rerank), and Summarize speaks for the whole issue.
  if (context.entityType === "item") return { similar: { itemId: context.entityId }, summarizeItemId: context.entityId };
  const excludeItemId = context.parent?.entityType === "item" ? context.parent.entityId : undefined;
  return {
    similar: { seedKey: context.entityId, excludeItemId },
    // RADD-1275: a page's image attachments may be shown to the vision role.
    imagesOf: context.entityType === "page" ? { entity_type: "page", entity_id: context.entityId } : undefined,
  };
}

/**
 * The read-mode AI menu (spec 103 follow-up) — this plugin's `content.read.action` (RADD-1395): a
 * sparkle button on RENDERED content — no edit mode, no selection needed. Query actions (Find
 * similar, Summarize) answer in the reading pane where the surface has one, else in this popover,
 * without touching the text; transform actions and the freeform prompt hand off to the editor via
 * the host's `transform`. Renders nothing when no gate lets any entry through.
 */
export function AiReadMenu({ text, context, transform, subject, className = "" }: ReadActionProps) {
  const label = `AI actions for ${subject}`;
  const { similar, summarizeItemId, imagesOf } = readingOf(context);
  const status = useAiStatus();
  const editorAi = useEditorAi();
  const openResults = useOpenAiResults();
  const [anchor, setAnchor] = useState<{ left: number; top: number } | null>(null);
  const [view, setView] = useState<View>("menu");
  const [summary, setSummary] = useState("");
  const [summaryState, setSummaryState] = useState<"streaming" | "done" | "error">("done");
  const [summaryError, setSummaryError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Issue-level summarize (spec 46 endpoint) — used instead of the text stream when the menu
  // speaks for the whole issue (the description).
  const itemSummary = useMutation({
    mutationFn: () => api.post<AiSummary>(itemSummarizePath(summarizeItemId ?? "")),
  });

  const aiEnabled = status.data?.enabled === true;
  const itemSummarizeOn = summarizeItemId !== undefined && status.data?.features[AiFeature.summarize] === true;
  const summarizeAction =
    summarizeItemId !== undefined
      ? undefined // whole-issue menus never fall back to text-only summarize
      : editorAi?.actions.find((action) => action.id === AiBuiltinEditorAction.summarize);
  const canQuery = aiEnabled && (similar !== undefined || summarizeAction !== undefined || itemSummarizeOn);
  const canTransform = editorAi !== null && transform !== undefined;

  const itemSeed = "itemId" in similar ? similar : undefined;
  const textSeed = "seedKey" in similar ? similar : undefined;
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
    setAnchor({ left: Math.min(rect.left, window.innerWidth - PANEL_WIDTH - 8), top: rect.bottom + 4 });
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
        AiEndpoint.editorStream,
        {
          action_id: AiBuiltinEditorAction.summarize,
          document: text,
          selection: "",
          ...(imagesOf ? { images_of: imagesOf } : {}),
        },
        controller.signal,
      );
      for await (const chunk of frames) setSummary((current) => current + chunk);
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
        data-ai-read-menu
        className={"rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer " + className}
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
              data-ai-read-panel
            >
              {view === "menu" ? (
                <div className="flex flex-col gap-1">
                  {canQuery && (
                    <ul className="flex flex-col">
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
                              openResults({ kind: "text-summary", text, imagesOf });
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
                          transform?.(aiTransform(run));
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
                        <SimilarCandidatesList candidates={similarResult.data?.candidates ?? []} onOpen={close} />
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
                      <ErrorText error={summaryError} />
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

function MenuEntry({ icon, label, onClick }: { icon: ReactNode; label: string; onClick: () => void }) {
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
