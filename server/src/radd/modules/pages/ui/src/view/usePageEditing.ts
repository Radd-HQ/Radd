import { useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ApiError, CommentSection, LiveRole, api, errorMessage, invalidateEntities, toast, useCommentFeed, useCurrentUser,
  useIsAuthenticated, useLiveSession, type AiRun, type InlineAnchorRef,
} from "@radd/plugin-sdk";
import { commentPath, pagePath } from "../endpoints";
import { Tag } from "../queries";
import type { Page, PageUpdate } from "../types";

/**
 * A page's edit session (spec 122): readers sit in the room as observers, Edit joins as an editor
 * on a shared document, and the elected saver autosaves. The spec-43 single-editor flow (Save
 * with `expected_version`; reload-or-overwrite on a 409) is the fallback when the room cannot be
 * joined. The room itself is the host's (collab stays an optional plugin): this reaches it
 * through the SDK's live-session bridge.
 */
export function usePageEditing(page: Page) {
  const queryClient = useQueryClient();
  const invalidate = () => void invalidateEntities(queryClient, Tag.page, Tag.space);
  // A visitor is answered as the Anyone principal (spec 121): only an account joins a room.
  const account = useCurrentUser();
  const me = useIsAuthenticated() ? account : null;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(page.body);
  // The live markdown as a ref: the saver reads it at write time, and a captured value would be
  // the draft as of the last render.
  const draftRef = useRef(page.body);
  /** The version the session was OPENED at — the optimistic-concurrency anchor. A realtime
   *  refetch may bump page.version mid-edit; saving must still 409 against what the author read. */
  const [editVersion, setEditVersion] = useState(page.version);
  const [conflict, setConflict] = useState(false);
  // A read-mode AI transform pending for the session about to open — the editor's initial run.
  const [pendingAiRun, setPendingAiRun] = useState<AiRun | null>(null);
  const [finishing, setFinishing] = useState(false);

  // RADD-1274: the open inline comments, handed to the editor so an AI review can count the
  // passages it removes. The same feed the rail reads, and only while editing.
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
  // Spec 122: a visitor never joins (D9); a reader is an observer; Edit is an editor. Each role
  // change is a fresh session.
  const collab = useLiveSession({
    pageId: page.id,
    role: !me ? null : editing ? LiveRole.editor : LiveRole.observer,
    user: me,
    getMarkdown: () => draftRef.current,
    onSaved: (saved) => {
      // Our own write: the version to anchor on if the room later refuses us and the
      // single-editor Save has to take over mid-session.
      setEditVersion(saved.version);
      invalidate();
    },
    onSaveError: (error) => toast(`Autosave failed: ${errorMessage(error)}`),
  });
  const save = useMutation({
    mutationFn: (body: PageUpdate) => api.patch<Page>(pagePath(page.id), body),
    onSuccess: () => { setEditing(false); setConflict(false); },
    onError: (error) => { if (error instanceof ApiError && error.status === 409) setConflict(true); },
    onSettled: invalidate,
  });

  return {
    editing, draft, editVersion, conflict, pendingAiRun, finishing, collab, inlineAnchors, save,
    /** The room refused us (or there is no account): the single-editor flow. */
    legacy: collab.failed || !me,
    onDraft: (markdown: string) => { draftRef.current = markdown; setDraft(markdown); },
    open: (run: AiRun | null) => {
      draftRef.current = page.body;
      setDraft(page.body);
      setEditVersion(page.version);
      setPendingAiRun(run);
      setEditing(true);
    },
    /** Leave the room: the final write first, if this client is the saver. */
    done: async () => {
      setFinishing(true);
      try { await collab.finish(); } finally {
        setFinishing(false);
        setEditing(false);
        setPendingAiRun(null);
        invalidate();
      }
    },
    cancel: () => { setEditing(false); setConflict(false); setPendingAiRun(null); },
    reload: () => { setConflict(false); setEditing(false); invalidate(); },
    resolveDetached: (ids: string[]) => resolveDetached.mutate(ids),
    invalidate,
  };
}

export type PageEditing = ReturnType<typeof usePageEditing>;
