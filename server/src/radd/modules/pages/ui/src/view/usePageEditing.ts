import { useCallback, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ApiError, CommentSection, LiveStatus, api, errorMessage, invalidateEntities, toast, useCommentFeed,
  useLiveDocument, type EditorTransform, type InlineAnchorRef, type LiveSave,
} from "@radd/plugin-sdk";
import { commentPath, pagePath } from "../endpoints";
import { Tag } from "../queries";
import type { Page, PageUpdate } from "../types";

/**
 * A page's edit session. A page asks for a LIVE SESSION (RADD-1397): when a plugin provides one
 * (spec 122's co-editing), readers sit in it as observers, Edit makes an editor on a shared document,
 * and the session decides when the shared copy is saved — through this page's own write, vouched
 * for by the session. Without one — no provider, a refusal, a visitor — the spec-43 single-editor
 * flow runs: Save with `expected_version`, reload-or-overwrite on a 409.
 */
export function usePageEditing(page: Page, canWrite: boolean) {
  const queryClient = useQueryClient();
  const invalidate = () => void invalidateEntities(queryClient, Tag.page, Tag.space);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(page.body);
  // The live markdown as a ref: a session's save reads it at write time, and a captured value
  // would be the draft as of the last render.
  const draftRef = useRef(page.body);
  /** The version the session was OPENED at — the optimistic-concurrency anchor. A realtime
   *  refetch may bump page.version mid-edit; saving must still 409 against what the author read. */
  const [editVersion, setEditVersion] = useState(page.version);
  const [conflict, setConflict] = useState(false);
  // A read action's transform pending for the session about to open — the editor's initial run.
  const [pendingTransform, setPendingTransform] = useState<EditorTransform | null>(null);
  const [finishing, setFinishing] = useState(false);

  // RADD-1274: the open inline comments, handed to the editor so a transform review can count
  // the passages it removes. The same feed the rail reads, and only while editing.
  const inlineFeed = useCommentFeed({ parentType: "page", parentId: page.id, section: CommentSection.inline, enabled: editing });
  const inlineAnchors = useMemo<InlineAnchorRef[]>(
    () => inlineFeed.comments
      .filter((comment) => comment.anchor && !comment.resolved_at)
      .map((comment) => ({ id: comment.id, anchor: comment.anchor! })),
    [inlineFeed.comments],
  );
  const resolveDetached = useMutation({
    mutationFn: (ids: string[]) => Promise.all(ids.map((id) => api.post(`${commentPath(id)}/resolve`))),
    onSuccess: (_result, ids) => toast(ids.length === 1
      ? "Resolved 1 comment whose passage was replaced."
      : `Resolved ${ids.length} comments whose passages were replaced.`),
    onSettled: () => void invalidateEntities(queryClient, Tag.comment),
  });
  /** A live session's save: this page's own write, vouched for by the session (spec 122's
   *  `collab_session` — the server skips the version check for a connected editor's writes). */
  const liveSave = useCallback(async (markdown: string, { session, final, keepalive }: LiveSave) => {
    const body: PageUpdate = { body: markdown, collab_session: session, final };
    try {
      const saved = await api.patch<Page>(pagePath(page.id), body, { keepalive });
      // Our own write: the version to anchor on if the session later ends and the
      // single-editor Save has to take over mid-edit.
      setEditVersion(saved.version);
      invalidate();
    } catch (error) {
      toast(`Autosave failed: ${errorMessage(error)}`, "error");
      throw error;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page.id]);
  const live = useLiveDocument({
    entityType: "page",
    entityId: page.id,
    canWrite,
    editing,
    getMarkdown: () => draftRef.current,
    save: liveSave,
  });
  const save = useMutation({
    mutationFn: (body: PageUpdate) => api.patch<Page>(pagePath(page.id), body),
    onSuccess: () => { setEditing(false); setConflict(false); },
    onError: (error) => { if (error instanceof ApiError && error.status === 409) setConflict(true); },
    onSettled: invalidate,
  });

  return {
    editing, draft, editVersion, conflict, pendingTransform, finishing, live, inlineAnchors, save,
    /** No live session: the single-editor flow. */
    legacy: live.status === LiveStatus.none,
    onDraft: (markdown: string) => { draftRef.current = markdown; setDraft(markdown); },
    open: (transform: EditorTransform | null) => {
      draftRef.current = page.body;
      setDraft(page.body);
      setEditVersion(page.version);
      setPendingTransform(transform);
      setEditing(true);
    },
    /** Leave the session: the final write first, when this client is the one that saves. */
    done: async () => {
      setFinishing(true);
      try { await live.finish(); } finally {
        setFinishing(false);
        setEditing(false);
        setPendingTransform(null);
        invalidate();
      }
    },
    cancel: () => { setEditing(false); setConflict(false); setPendingTransform(null); },
    reload: () => { setConflict(false); setEditing(false); invalidate(); },
    resolveDetached: (ids: string[]) => resolveDetached.mutate(ids),
    invalidate,
  };
}

export type PageEditing = ReturnType<typeof usePageEditing>;
