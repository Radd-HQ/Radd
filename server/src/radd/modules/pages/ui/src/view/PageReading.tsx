import type { RefObject } from "react";
import { Pencil } from "lucide-react";
import { Button, Slot, SlotId, sendTaskToggle, type EditorTransform } from "@radd/plugin-sdk";
import { pageTasksPath } from "../endpoints";
import type { Page } from "../types";
import { PageBody } from "./PageBody";
import { PageBacklinksPanel } from "./PageBacklinksPanel";
import { PageComments } from "./PageComments";
import { PageLinkedItems } from "./PageLinkedItems";

/** The page in read mode: its body (with the contributed read actions and Edit), then what is
 *  linked to it and the discussion about it. */
export function PageReading({ page, bodyRef, canWrite, canComment, onEdit, onRendered, onChanged }: {
  page: Page;
  /** The rendered body — the inline comments' coordinate space. */
  bodyRef: RefObject<HTMLDivElement | null>;
  canWrite: boolean;
  canComment: boolean;
  /** Open the editor, with a read action's transform to run first when there is one. */
  onEdit: (transform: EditorTransform | null) => void;
  /** The body finished rendering (anchors re-scan). */
  onRendered: () => void;
  onChanged: () => void;
}) {
  return (
    <>
      <div ref={bodyRef}>
        {page.body ? (
          <div className="mt-3 rounded-md px-1.5 py-1">
            <div className="mb-2 flex flex-wrap items-center justify-end gap-1">
              {/* Contributed read actions (RADD-1395) for every reader; a transform — which
                  opens the editor with it — only for writers. */}
              <Slot
                id={SlotId.contentReadAction}
                text={page.body}
                context={{ entityType: "page", entityId: page.id }}
                transform={canWrite ? onEdit : undefined}
                subject="this page"
              />
              {canWrite && (
                <Button variant="ghost" size="sm" onClick={() => onEdit(null)} aria-label="Edit page" title="Edit page">
                  <Pencil size={12} aria-hidden />
                  Edit page
                </Button>
              )}
            </div>
            <PageBody
              text={page.body}
              onReady={onRendered}
              // RADD-1296: tick a checklist box without opening the editor — a versioned save the
              // co-editing guard can refuse.
              onToggleTask={canWrite
                ? async (toggle) => { await sendTaskToggle(pageTasksPath(page.id), toggle, page.body); onChanged(); }
                : undefined}
            />
          </div>
        ) : canWrite ? (
          <button type="button" onClick={() => onEdit(null)}
            className="mt-3 rounded-md border border-transparent px-1.5 py-1 text-left text-[13px] text-fg-faint hover:border-subtle hover:text-fg-secondary cursor-pointer">
            Write something…
          </button>
        ) : (
          <p className="mt-3 px-1.5 text-[13px] text-fg-faint">This page is empty.</p>
        )}
      </div>

      <PageLinkedItems pageId={page.id} canWrite={canWrite} />

      {/* Backlinks stay automatic: "what points at me" has no inline form (RADD-944 removed the subpage index). */}
      <PageBacklinksPanel pageId={page.id} />

      <PageComments pageId={page.id} canComment={canComment} />
    </>
  );
}
