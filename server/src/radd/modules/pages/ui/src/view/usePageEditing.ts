import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ApiError, CommentSection, LiveStatus, api, errorMessage, invalidateEntities, toast, useCommentFeed,
  useLiveDocument, type EditorTransform, type InlineAnchorRef, type LiveSave,
} from "@radd/plugin-sdk";
import { commentPath, pagePath } from "../endpoints";
import { Tag } from "../queries";
import type { Page, PageUpdate } from "../types";

/**
 * A page's edit session (RADD-1397). With a LIVE SESSION from a plugin, readers observe, Edit joins
 * a shared document, and the session decides when it is saved — through this page's own write,
 * vouched for by the session. Without one (no provider, a refusal, a visitor): Save with
 * `expected_version`, reload-or-overwrite on a 409.
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
  // RADD-1461: the page's OWN editor was opened with no live session in sight. A session that shows
  // up later (the plugin enabled mid-edit) is offered, never imposed — the bound editor would replace
  // the draft with the shared copy. While set, this client is in the room as a READER; `joinLive`
  // turns that into an editor session that keeps the draft.
  const [ownEditor, setOwnEditor] = useState(false);
  const [keepDraft, setKeepDraft] = useState(false);

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
    editing: editing && !ownEditor,
    keepDraft,
    getMarkdown: () => draftRef.current,
    save: liveSave,
  });
  /** Back to reading, whichever editor was open. */
  const leaveEditor = () => {
    setEditing(false);
    setOwnEditor(false);
    setKeepDraft(false);
    setPendingTransform(null);
  };
  const save = useMutation({
    mutationFn: (body: PageUpdate) => api.patch<Page>(pagePath(page.id), body),
    onSuccess: () => { leaveEditor(); setConflict(false); },
    onError: (error) => { if (error instanceof ApiError && error.status === 409) setConflict(true); },
    onSettled: invalidate,
  });
  /** A live session became available while the page's own editor is open. */
  const liveOffered = editing && ownEditor && live.status !== LiveStatus.none;
  // Nothing typed yet: the session costs the person nothing, so it is joined without asking.
  useEffect(() => {
    if (liveOffered && draft === page.body) setOwnEditor(false);
  }, [liveOffered, draft, page.body]);

  return {
    editing, draft, editVersion, conflict, pendingTransform, finishing, live, inlineAnchors, save, liveOffered,
    /** No live session: the single-editor flow. Once the page's own editor is open it stays the
     *  page's own until the person joins a session that appeared later (`joinLive`). */
    legacy: ownEditor || live.status === LiveStatus.none,
    onDraft: (markdown: string) => { draftRef.current = markdown; setDraft(markdown); },
    open: (transform: EditorTransform | null) => {
      draftRef.current = page.body;
      setDraft(page.body);
      setEditVersion(page.version);
      setPendingTransform(transform);
      // No session in sight — none offered, none still arriving — is the page's own editor from the
      // start; a session that turns up afterwards is offered, not imposed.
      setOwnEditor(live.status === LiveStatus.none);
      setKeepDraft(false);
      setEditing(true);
    },
    /** Join the session that appeared while the page's own editor was open, draft and all: it seeds
     *  an empty shared copy, or lands in a non-empty one as this person's change. */
    joinLive: () => {
      setKeepDraft(true);
      // The first editor already ran it; its result is in the draft.
      setPendingTransform(null);
      setOwnEditor(false);
    },
    /** Leave the session: the final write first, when this client is the one that saves. */
    done: async () => {
      setFinishing(true);
      try { await live.finish(); } finally {
        setFinishing(false);
        leaveEditor();
        invalidate();
      }
    },
    cancel: () => { leaveEditor(); setConflict(false); },
    reload: () => { setConflict(false); leaveEditor(); invalidate(); },
    resolveDetached: (ids: string[]) => resolveDetached.mutate(ids),
    invalidate,
  };
}
