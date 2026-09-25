import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ComponentProps } from "react";
import { LazyRichViewer } from "./LazyRichViewer";
import { api } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { Button } from "../Button";
import { ErrorText } from "../ErrorText";

/** A signature is a reversible annotation over an exact suffix of the original text. */
export function EmailBody({ signature, parent, canRestore, ...props }: ComponentProps<typeof LazyRichViewer> & {
  signature?: string | null; parent?: { kind: "item" | "comment"; id: string }; canRestore?: boolean;
}) {
  const client = useQueryClient();
  const restore = useMutation({ mutationFn: () => parent ? api.post(`/mail/signatures/${parent.kind}/${parent.id}/restore`, {}) : Promise.reject(new Error("Missing signature parent")),
    onSuccess: () => invalidateEntities(client, Entity.item, Entity.comment) });
  const start = signature ? props.text.indexOf(signature) : -1;
  const end = start + (signature?.length ?? 0);
  const hidden = signature && start > 0 && props.text.slice(0, start).trim()
    && props.text.indexOf(signature, start + 1) < 0
    && props.text[start - 1] === "\n"
    && (end === props.text.length || props.text[end] === "\n") ? signature : null;
  return <>
    <LazyRichViewer {...props} text={hidden ? props.text.slice(0, start) : props.text} />
    {hidden && <details className="mt-2 text-sm text-fg-muted">
      <summary className="w-fit cursor-pointer text-xs">Show signature</summary>
      <div className="mt-2 whitespace-pre-wrap border-l border-subtle pl-3">{hidden}</div>
      {canRestore && parent && <Button size="sm" variant="ghost" disabled={restore.isPending} onClick={() => restore.mutate()}>Not a signature</Button>}
      {restore.isError && <ErrorText error={restore.error} />}
    </details>}
    {hidden && props.text.slice(end).trim() && <LazyRichViewer text={props.text.slice(end)} />}
  </>;
}
