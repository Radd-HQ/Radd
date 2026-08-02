import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useStorageChoice } from "../components/attachments/StorageChoiceProvider";
import { uploadAttachment } from "./attachments";
import { Entity, invalidateEntities } from "./cache";
import { uploadContextQuery } from "./queries";
import type { Attachment, AttachmentTarget, UploadContext } from "./types";

/** Thrown when the storage prompt is dismissed — the whole gesture aborts;
 * callers treat it as "never mind", not as a failure to report. */
export class UploadCanceledError extends Error {
  constructor() {
    super("Upload canceled");
    this.name = "UploadCanceledError";
  }
}

/**
 * The one attachment-upload seam (spec 102). Every surface that uploads —
 * attachment grid, description/comment/pages image paste — goes through here so
 * the storage prompt behaves identically everywhere:
 * - one gesture = ONE prompt covering all its files; dismiss cancels them all
 *   (rejects with UploadCanceledError so editor inserts abort cleanly);
 * - exactly one selectable host → sent silently, no prompt;
 * - the context read is cached (~30s), so bursts share a single probe.
 */
export function useAttachmentUploader(
  target: AttachmentTarget,
): (files: File[]) => Promise<Attachment[]> {
  const queryClient = useQueryClient();
  const { choose } = useStorageChoice();
  const { entityType, entityId } = target;

  return useCallback(
    async (files: File[]) => {
      if (files.length === 0) return [];
      // fetchQuery honors staleTime — a fresh cache entry answers without a request.
      let context: UploadContext | null = null;
      try {
        context = await queryClient.fetchQuery(
          uploadContextQuery(files.map((file) => file.type)),
        );
      } catch {
        // Context unreachable — never block the upload; the chain still routes server-side.
      }
      let hostId: string | undefined;
      if (context?.ask_user && context.options.length >= 2) {
        const picked = await choose(context.options);
        if (picked === null) throw new UploadCanceledError();
        hostId = picked;
      } else if (context?.options.length === 1) {
        hostId = context.options[0].id;
      }
      const uploaded: Attachment[] = [];
      try {
        for (const file of files) {
          uploaded.push(await uploadAttachment({ entityType, entityId }, file, { hostId }));
        }
      } finally {
        // Even a partial batch changed the attachment list — refresh it.
        if (uploaded.length > 0) void invalidateEntities(queryClient, Entity.attachment);
      }
      return uploaded;
    },
    [queryClient, choose, entityType, entityId],
  );
}
