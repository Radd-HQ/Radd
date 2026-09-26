/**
 * The host's document and comment surfaces, handed to the plugin SDK so the wiki renders the same
 * editor, viewer, markdown, reading pane and comment kit as the issue page without importing host
 * code. Heavy surfaces stay lazy (the editor engine and markdown load on first render). What plugins
 * ADD to the editor arrives through its extension points, not through here.
 */
import { Suspense, lazy, useMemo, type ComponentProps } from "react";
import { provideHostComponents, type RichEditorProps } from "@radd/plugin-sdk";
import { LazyRichEditor } from "./components/editor/LazyRichEditor";
import { LazyRichViewer } from "./components/editor/LazyRichViewer";
import { ToolbarExtraButton } from "./components/editor/ToolbarExtraButton";
import { ReadingPane } from "./components/reading/ReadingPane";
import type { AttachmentTarget } from "./lib/types";
import { useImageUploader } from "./lib/useAttachmentUploader";
import { apiParentCommentsPath } from "./lib/constants";
import { CommentHistory } from "./components/CommentHistory";
import { CopyCommentLink } from "./components/comments/CopyCommentLink";
import { ResolveThreadButton, ThreadBadge, ThreadFilter, repliesLabel, threadRuleClass } from "./components/comments/ThreadResolution";
import { useThreadExpansion } from "./components/comments/useThreadExpansion";
import { commentHref, useLandOnComment, useLinkedComment } from "./lib/comment-links";
import { chronologicalComments, commentFeedQuery } from "./lib/queries/comment-feed";
import { sendTaskToggle } from "./lib/task-toggle";
import { useInfiniteQuery } from "@tanstack/react-query";

const Markdown = lazy(() => import("./lib/markdown").then((module) => ({ default: module.Markdown })));
const CommentReplies = lazy(() =>
  import("./components/comments/CommentReplies").then((module) => ({ default: module.CommentReplies })),
);

type EditorProps = Omit<RichEditorProps, "attachTo"> & { onUploadImage?: (file: File) => Promise<string> };

function Editor(props: EditorProps) {
  return <LazyRichEditor {...props} />;
}

function UploadingEditor({ attachTo, ...props }: EditorProps & { attachTo: NonNullable<RichEditorProps["attachTo"]> }) {
  // The SDK names the parent by its registered type; the host types it as the wire enum.
  const onUploadImage = useImageUploader(attachTo as AttachmentTarget);
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
  // Eager: its children are the page, and a lazy pane would remount them when it loads.
  ReadingPane,
  EditorToolbarButton: ToolbarExtraButton,

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
