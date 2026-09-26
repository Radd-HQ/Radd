/**
 * The host's document and comment surfaces, handed to the plugin SDK (RADD-1392) so the wiki —
 * the pages plugin's bundled UI — renders the same editor, viewer, markdown, AI menu, live room
 * and comment kit as the issue page, without importing host code. Heavy surfaces stay lazy: the
 * editor engine, the markdown renderer and the AI panels load when one first renders.
 */
import { Suspense, lazy, useCallback, useMemo, type ComponentProps } from "react";
import { provideHostComponents, type RichEditorProps } from "@radd/plugin-sdk";
import { LazyRichEditor } from "./components/editor/LazyRichEditor";
import { LazyRichViewer } from "./components/editor/LazyRichViewer";
import { EditingNow } from "./components/editor/collab/EditingNow";
import { AiResultsPane } from "./components/items/AiResultsPane";
import { useCollabSession } from "./components/editor/collab/useCollabSession";
import type { CollabRoom } from "./components/editor/collab/provider";
import type { AttachmentTarget } from "./lib/types";
import { useAttachmentUploader } from "./lib/useAttachmentUploader";
import { attachmentUrl, apiParentCommentsPath } from "./lib/constants";
import { CommentHistory } from "./components/CommentHistory";
import { CopyCommentLink } from "./components/comments/CopyCommentLink";
import { ResolveThreadButton, ThreadBadge, ThreadFilter, repliesLabel, threadRuleClass } from "./components/comments/ThreadResolution";
import { useThreadExpansion } from "./components/comments/useThreadExpansion";
import { commentHref, useLandOnComment, useLinkedComment } from "./lib/comment-links";
import { chronologicalComments, commentFeedQuery } from "./lib/queries/comment-feed";
import { sendTaskToggle } from "./lib/task-toggle";
import { useInfiniteQuery } from "@tanstack/react-query";

const Markdown = lazy(() => import("./lib/markdown").then((module) => ({ default: module.Markdown })));
const AiReadMenu = lazy(() => import("./components/editor/AiReadMenu").then((module) => ({ default: module.AiReadMenu })));
const CommentReplies = lazy(() =>
  import("./components/comments/CommentReplies").then((module) => ({ default: module.CommentReplies })),
);

type EditorProps = Omit<RichEditorProps, "attachTo"> & { onUploadImage?: (file: File) => Promise<string> };

/** A live room is the host's CollabRoom behind the SDK's opaque handle. */
function Editor({ live, ...props }: EditorProps) {
  const room = live as CollabRoom | undefined;
  return (
    <LazyRichEditor
      {...props}
      collab={room && { doc: room.doc, provider: room.provider, awareness: room.awareness, seed: room.seed, template: props.value }}
    />
  );
}

function UploadingEditor({ attachTo, ...props }: EditorProps & { attachTo: NonNullable<RichEditorProps["attachTo"]> }) {
  // The SDK names the parent by its registered type; the host types it as the wire enum.
  const upload = useAttachmentUploader(attachTo as AttachmentTarget);
  const onUploadImage = useCallback(async (file: File) => {
    const [attachment] = await upload([file]);
    return attachmentUrl(attachment.id);
  }, [upload]);
  return <Editor {...props} onUploadImage={onUploadImage} />;
}

function RichEditor({ attachTo, ...props }: RichEditorProps) {
  return attachTo ? <UploadingEditor attachTo={attachTo} {...props} /> : <Editor {...props} />;
}

/** One feed per parent and section, shared with the issue page's comment kit. */
function useCommentFeed({ parentType, parentId, section, unresolvedOnly = false, through, enabled = true }: {
  parentType: string; parentId: string; section: Parameters<typeof commentFeedQuery>[2];
  unresolvedOnly?: boolean; through?: string; enabled?: boolean;
}) {
  const feed = useInfiniteQuery({
    ...commentFeedQuery(["comments", parentType, parentId], apiParentCommentsPath(parentType, parentId), section, unresolvedOnly, through),
    enabled,
  });
  // Stable until the feed changes: the wiki's inline rail re-scans its anchors whenever the list
  // is a new array, and a fresh one per render re-rendered it forever.
  const comments = useMemo(() => chronologicalComments(feed.data?.pages), [feed.data]);
  return {
    comments,
    hasOlder: feed.hasNextPage,
    loadingOlder: feed.isFetchingNextPage,
    loadOlder: () => feed.fetchNextPage(),
    isPending: feed.isPending,
    isError: feed.isError,
    error: feed.error,
  };
}

provideHostComponents({
  RichEditor,
  RichViewer: LazyRichViewer,
  Markdown: (props) => (
    <Suspense fallback={<div className="whitespace-pre-wrap text-[13px] text-fg">{props.text}</div>}>
      <Markdown {...props} />
    </Suspense>
  ),
  AiReadMenu: (props) => <Suspense fallback={null}><AiReadMenu {...props} /></Suspense>,
  // Eager: its children are the page, and a lazy pane would remount them when it loads.
  AiResultsPane,
  EditingNow,
  useLiveSession: useCollabSession,

  // The comment kit's rows come from the same API as the host's `Comment`.
  CommentReplies: (props) => (
    <Suspense fallback={<p role="status" className="text-xs text-fg-muted">Loading replies…</p>}>
      <CommentReplies {...(props as unknown as ComponentProps<typeof CommentReplies>)} />
    </Suspense>
  ),
  CommentHistory,
  CopyCommentLink,
  ThreadBadge,
  ThreadFilter,
  ResolveThreadButton,
  useCommentFeed,
  useLinkedComment,
  useLandOnComment,
  useThreadExpansion,
  commentHref,
  repliesLabel,
  threadRuleClass,
  sendTaskToggle,
});
