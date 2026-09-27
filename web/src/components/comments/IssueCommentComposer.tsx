import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CommentComposerMode, type CommentComposerModeValue } from "@radd/plugin-sdk";
import { CommentVisibility, type CommentVisibilityValue } from "@radd-plugin-ui/comments/visibility";
import { api, errorMessage } from "../../lib/api";
import { apiCannedRenderPath, apiItemCommentsPath } from "../../lib/constants";
import { cannedResponsesQuery, queryKeys } from "../../lib/queries";
import type { CannedRender, Comment, CommentCreate } from "../../lib/types";
import { LazyRichEditor as RichEditor } from "../editor/LazyRichEditor";
import type { QuickAction } from "../items/quick-actions";
import { COMMENT_AUDIENCE_COPY } from "../items/CommentAudienceNames";
import { Select } from "../Select";
import { TeamAudience } from "../teams/TeamAudience";
import { CommentComposer } from "./CommentComposer";
import { SegmentedChoice } from "./SegmentedChoice";

const AUDIENCES = [
  { value: CommentVisibility.public, label: "Public reply" },
  // The warning callout's tokens, like the internal editor under it: legible in both themes.
  { value: CommentVisibility.internal, label: "Internal note", activeClassName: "bg-callout-warning-fill text-callout-warning-ink" },
] as const;

/** The submit's words: what the post will be, and who will read it. */
function submitLabel(mode: CommentComposerModeValue, internal: boolean): string {
  if (mode === CommentComposerMode.thread) return internal ? "Start internal thread" : "Start thread";
  return internal ? "Post internal note" : "Comment";
}

/**
 * The issue's composer (spec 02/07, RADD-1448): the shared `CommentComposer` with the issue's
 * extras — the Public reply | Internal note audience for readers of internal notes, the teams an
 * internal note is for, canned responses rendered against this issue, and `/` quick actions.
 * Cancel keeps the draft (and its audience); a post that lands closes and clears it.
 */
export function IssueCommentComposer({
  itemId,
  canReadInternal,
  quickActions,
  onUploadImage,
}: {
  itemId: string;
  /** comment.read_internal: may write an internal note. */
  canReadInternal: boolean;
  quickActions: QuickAction[];
  onUploadImage: (file: File) => Promise<string>;
}) {
  const queryClient = useQueryClient();
  const { data: canned } = useQuery(cannedResponsesQuery());
  const [mode, setMode] = useState<CommentComposerModeValue | null>(null);
  const [body, setBody] = useState("");
  // The rich editor is uncontrolled: remount it to show text put in from outside (a canned response).
  const [editorKey, setEditorKey] = useState(0);
  const [visibility, setVisibility] = useState<CommentVisibilityValue>(CommentVisibility.public);
  const [visibleTeams, setVisibleTeams] = useState<string[]>([]);
  const internal = canReadInternal && visibility === CommentVisibility.internal;

  const create = useMutation({
    mutationFn: (payload: CommentCreate) => api.post<Comment>(apiItemCommentsPath(itemId), payload),
    onSuccess: () => {
      setMode(null);
      setBody("");
      setVisibility(CommentVisibility.public);
      setVisibleTeams([]);
      void queryClient.invalidateQueries({ queryKey: queryKeys.comments(itemId) });
      // comment_count lives on the item (spec 02) — refresh it too.
      void queryClient.invalidateQueries({ queryKey: queryKeys.item(itemId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.allowedTransitions(itemId) });
    },
  });
  const submit = () => {
    const trimmed = body.trim();
    if (!trimmed || !mode || create.isPending) return;
    create.mutate({
      body: trimmed,
      is_thread: mode === CommentComposerMode.thread,
      visibility,
      visible_to_teams: internal ? visibleTeams : [],
    });
  };
  const insertCanned = (picked: string) => {
    const response = (canned ?? []).find((row) => row.id === picked);
    if (!response) return;
    const insert = (text: string) => {
      setBody((current) => (current ? `${current}\n${text}` : text));
      setEditorKey((key) => key + 1);
    };
    // Spec 66: {{token}} variables resolve against THIS item — fall back to the raw body if the
    // render call fails.
    api
      .get<CannedRender>(apiCannedRenderPath(response.id), { query: { item_id: itemId } })
      .then((rendered) => insert(rendered.body))
      .catch(() => insert(response.body));
  };

  return (
    <CommentComposer
      mode={mode}
      onMode={(next) => {
        create.reset();
        setMode(next);
      }}
      submitLabel={submitLabel(mode ?? CommentComposerMode.comment, internal)}
      canSubmit={body.trim() !== ""}
      pending={create.isPending}
      error={create.isError ? errorMessage(create.error) : undefined}
      onSubmit={submit}
      controls={
        canReadInternal && (
          <SegmentedChoice label="Comment visibility" value={visibility} options={AUDIENCES} onChange={setVisibility} />
        )
      }
    >
      {internal && <TeamAudience value={visibleTeams} onChange={setVisibleTeams} {...COMMENT_AUDIENCE_COPY} />}
      {(canned ?? []).length > 0 && (
        <Select
          value=""
          onChange={insertCanned}
          aria-label="Insert canned response"
          size="sm"
          className="self-start"
          placeholder="Insert canned response…"
          options={(canned ?? []).map((response) => ({ value: response.id, label: response.title }))}
        />
      )}
      <RichEditor
        key={editorKey}
        value={body}
        onChange={setBody}
        autoFocus
        onUploadImage={onUploadImage}
        placeholder={
          mode === CommentComposerMode.thread
            ? internal ? "Start an internal thread…" : "Start a thread…"
            : internal ? "Write an internal note…" : "Write a comment…"
        }
        onSubmitShortcut={submit}
        quickActions={quickActions}
        // Callout-warning tokens, computed per theme (RADD-900). `!` stays because RichEditor
        // appends this AFTER its own border/bg classes, where stylesheet order decides the winner.
        className={internal ? "!border-callout-warning-border/60 !bg-callout-warning-fill" : ""}
      />
    </CommentComposer>
  );
}
