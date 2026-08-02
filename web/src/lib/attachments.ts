import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "./api";
import { Entity, invalidateEntities } from "./cache";
import { API_BASE, apiAttachmentPath, apiAttachmentsPath } from "./constants";
import type { Attachment, AttachmentTarget } from "./types";

/**
 * Multipart upload to the canonical polymorphic endpoint — plain fetch because
 * the typed api client JSON-encodes bodies; everything else (cookies, error
 * shape) matches it. Prefer routing uploads through `useAttachmentUploader`,
 * which handles the spec-102 storage prompt before calling here.
 */
export async function uploadAttachment(
  target: AttachmentTarget,
  file: File,
  options: { hostId?: string } = {},
): Promise<Attachment> {
  const form = new FormData();
  form.append("file", file);
  form.append("entity_type", target.entityType);
  form.append("entity_id", target.entityId);
  // The uploader's storage pick (spec 102) — the routing chain still arbitrates
  // server-side, so a stale or forged choice can never reach a hidden host.
  if (options.hostId) form.append("chosen_host_id", options.hostId);
  const response = await fetch(`${API_BASE}${apiAttachmentsPath()}`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail ?? detail;
    } catch {
      // non-JSON error body — keep statusText
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as Attachment;
}

/** Mirror of the backend's inline rule: only non-SVG images render in-page. */
export function isInlineImage(attachment: Pick<Attachment, "content_type">): boolean {
  const type = attachment.content_type.toLowerCase();
  return type.startsWith("image/") && type !== "image/svg+xml";
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function useDeleteAttachment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (attachmentId: string) => api.delete<void>(apiAttachmentPath(attachmentId)),
    onSettled: () => invalidateEntities(queryClient, Entity.attachment),
  });
}
