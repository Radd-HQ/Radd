import { useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, FileSearch, Sparkles, X } from "lucide-react";
import type { ReadActionProps } from "@radd/plugin-sdk";
import { AiActionPicker } from "../editor/ActionPicker";
import { useEditorAi } from "../editor/gate";
import { aiTransform } from "../editor/transform";
import { useAiStatus } from "../queries";
import { AiResultsBody } from "../results/ResultsBody";
import { useOpenAiResults } from "../results/open";
import { AiBuiltinEditorAction, AiFeature, type AiResultRequest, type ImagesOf, type SimilarSeed } from "../types";

const PANEL_WIDTH = 320;

/** The popover shows the menu, or an answer where the surface has no reading pane. */
type View = "menu" | AiResultRequest;

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
 * The read-mode AI menu (`content.read.action`): a sparkle button on RENDERED content. Find similar
 * and Summarize answer in the reading pane where the surface has one, else in this popover;
 * transform actions and the freeform prompt hand off to the editor through the host's `transform`.
 * Renders nothing when no gate lets any entry through.
 */
export function AiReadMenu({ text, context, transform, subject, className = "" }: ReadActionProps) {
  const label = `AI actions for ${subject}`;
  const { similar, summarizeItemId, imagesOf } = readingOf(context);
  const status = useAiStatus();
  const editorAi = useEditorAi();
  const openResults = useOpenAiResults();
  const [anchor, setAnchor] = useState<{ left: number; top: number } | null>(null);
  const [view, setView] = useState<View>("menu");
  const buttonRef = useRef<HTMLButtonElement>(null);

  const aiEnabled = status.data?.enabled === true;
  const itemSummarizeOn = summarizeItemId !== undefined && status.data?.features[AiFeature.summarize] === true;
  const summarizeAction =
    summarizeItemId !== undefined
      ? undefined // whole-issue menus never fall back to text-only summarize
      : editorAi?.actions.find((action) => action.id === AiBuiltinEditorAction.summarize);
  const canQuery = aiEnabled;
  const canTransform = editorAi !== null && transform !== undefined;

  // An answer's stream stops when its body unmounts: on Back, on close, or with the menu.
  const close = () => {
    setAnchor(null);
    setView("menu");
  };
  const show = (request: AiResultRequest) => {
    if (!openResults) return setView(request);
    openResults(request);
    close();
  };

  if (text.trim() === "" || (!canQuery && !canTransform)) return null;

  const open = () => {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    setView("menu");
    setAnchor({ left: Math.min(rect.left, window.innerWidth - PANEL_WIDTH - 8), top: rect.bottom + 4 });
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
                        onClick={() => show({ kind: "similar", seed: similar, text })}
                      />
                      {itemSummarizeOn && summarizeItemId !== undefined && (
                        <MenuEntry
                          icon={<Sparkles size={12} aria-hidden />}
                          label="Summarize issue"
                          onClick={() => show({ kind: "item-summary", itemId: summarizeItemId })}
                        />
                      )}
                      {summarizeAction && (
                        <MenuEntry
                          icon={<Sparkles size={12} aria-hidden />}
                          label={summarizeAction.label}
                          onClick={() => show({ kind: "text-summary", text, imagesOf })}
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
                      onClick={() => setView("menu")}
                      className="flex items-center gap-1 rounded px-1 py-0.5 text-[11px] text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
                    >
                      <ArrowLeft size={11} aria-hidden />
                      {view.kind === "similar" ? "Similar issues" : "Summary"}
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
                    <AiResultsBody request={view} onOpen={close} />
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
