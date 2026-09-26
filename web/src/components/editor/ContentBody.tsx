import type { ComponentProps } from "react";
import { Slot, SlotId, useContentBodyClaim, type ContentContext } from "@radd/plugin-sdk";
import { LazyRichViewer } from "./LazyRichViewer";

type ViewerProps = ComponentProps<typeof LazyRichViewer>;

/**
 * A rendered BODY — an issue's description, a comment, a reply (RADD-1401). The host's viewer
 * draws it, unless a plugin's `content.body` contribution claims the record the body came from;
 * then that contribution draws it, through `renderText` for the text itself. The host names no
 * claimant and knows nothing that makes a body special. Withdrawn, or throwing, the claimant falls
 * back to the plain viewer, so a body is never lost to a plugin.
 */
export function ContentBody({ record, context, canEdit = false, ...viewer }: ViewerProps & {
  /** The row the body belongs to, as the server sent it. */
  record: object;
  context: ContentContext;
  /** Whether this reader may change the content (its author, a project manager). */
  canEdit?: boolean;
}) {
  const claim = useContentBodyClaim(record);
  const plain = <LazyRichViewer {...viewer} />;
  if (!claim) return plain;
  // A leading part's checklist is numbered from the body's start, so it stays interactive; any
  // other part would toggle the wrong task, so it is drawn read-only.
  const renderText = (part: string) => (
    <LazyRichViewer {...viewer} text={part} onToggleTask={viewer.text.startsWith(part) ? viewer.onToggleTask : undefined} />
  );
  return (
    <Slot
      id={SlotId.contentBody}
      match={claim.id}
      owner={claim.plugin}
      fallback={plain}
      errorFallback={plain}
      text={viewer.text}
      record={record}
      context={context}
      canEdit={canEdit}
      renderText={renderText}
    />
  );
}
