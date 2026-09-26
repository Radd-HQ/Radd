import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, ErrorText, api, contentBody, invalidateEntities, type ContentBodyProps } from "@radd/plugin-sdk";

/**
 * How a MAILED body reads (RADD-1401, before that the host's `EmailBody`): intake detects the
 * sender's signature and records it on the issue or comment as `email_signature`, an annotation
 * over an exact suffix of the stored text — the text itself is never cut. This contribution claims
 * every body whose record carries one, draws the text above it through the host's viewer, folds
 * the signature under "Show signature", and lets someone who may edit the content say "Not a
 * signature", which drops the annotation (`POST /mail/signatures/{kind}/{id}/restore`). With the
 * plugin off, the host draws the whole text as it would any other body.
 */

/** The parents intake annotates; each has its own restore route. */
const RESTORABLE = new Set(["item", "comment"]);

function signatureOf(record: object): string | null {
  const value = (record as { email_signature?: unknown }).email_signature;
  return typeof value === "string" && value !== "" ? value : null;
}

/** Where `signature` sits in `text` — only as the one, whole-line suffix it was recorded as, with
 *  something above it; anything else draws the text unfolded. */
function foldAt(text: string, signature: string): { start: number; end: number } | null {
  const start = text.indexOf(signature);
  const end = start + signature.length;
  if (start <= 0 || !text.slice(0, start).trim()) return null;
  if (text.indexOf(signature, start + 1) >= 0) return null;
  if (text[start - 1] !== "\n" || (end !== text.length && text[end] !== "\n")) return null;
  return { start, end };
}

function SignedBody({ text, record, context, canEdit, renderText }: ContentBodyProps) {
  const client = useQueryClient();
  const signature = signatureOf(record);
  const restore = useMutation({
    mutationFn: () => api.post(`/mail/signatures/${context.entityType}/${context.entityId}/restore`, {}),
    onSuccess: () => invalidateEntities(client, "item", "comment"),
  });
  const fold = signature ? foldAt(text, signature) : null;
  if (!signature || !fold) return <>{renderText(text)}</>;
  const trailing = text.slice(fold.end);
  return (
    <div data-mail-signed={context.entityId}>
      {renderText(text.slice(0, fold.start))}
      <details className="mt-2 text-sm text-fg-muted">
        <summary className="w-fit cursor-pointer text-xs">Show signature</summary>
        <div className="mt-2 whitespace-pre-wrap border-l border-subtle pl-3">{signature}</div>
        {canEdit && RESTORABLE.has(context.entityType) && (
          <Button size="sm" variant="ghost" disabled={restore.isPending} onClick={() => restore.mutate()}>
            Not a signature
          </Button>
        )}
        {restore.isError && <ErrorText error={restore.error} />}
      </details>
      {trailing.trim() && renderText(trailing)}
    </div>
  );
}

/** The `content.body` claim: every record intake annotated with a signature. */
export const signedBody = contentBody({
  id: "mailintake.signature",
  label: "Folded email signatures",
  claims: (record) => signatureOf(record) !== null,
  render: (props) => <SignedBody {...props} />,
});
