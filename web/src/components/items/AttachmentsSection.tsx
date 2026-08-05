import { useRef, useState, type DragEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { FileText, Lock, LockOpen, Upload, X } from "lucide-react";
import { errorMessage } from "../../lib/api";
import { formatSize, isInlineImage, useDeleteAttachment } from "../../lib/attachments";
import { UploadCanceledError, useAttachmentUploader } from "../../lib/useAttachmentUploader";
import { attachmentUrl } from "../../lib/constants";
import { attachmentsQuery } from "../../lib/queries";
import { AttachmentParentType, type Attachment, type Item } from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { AccessGrantsEditor } from "../settings/AccessGrantsEditor";

/**
 * Attachment grid on the issue view (spec 29): image thumbnails inline, other
 * files as chips; upload via button or drag-drop (the editor's paste path
 * uploads here too), routed through the storage-choice prompt (spec 102).
 * Delete = uploader or project admin (server-enforced). The lock affordance
 * opens the generic grants editor — read grants restrict who sees the file.
 */
export function AttachmentsSection({ item, canEdit }: { item: Item; canEdit: boolean }) {
  const target = { entityType: AttachmentParentType.item, entityId: item.id };
  const { data: attachments } = useQuery(attachmentsQuery(target));
  const uploadFiles = useAttachmentUploader(target);
  const upload = useMutation({ mutationFn: uploadFiles });
  const remove = useDeleteAttachment();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [aclTarget, setAclTarget] = useState<Attachment | null>(null);

  const uploadAll = (files: File[]) => {
    if (files.length > 0) upload.mutate(files);
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragOver(false);
    if (canEdit) uploadAll([...event.dataTransfer.files]);
  };

  const list = attachments ?? [];
  if (list.length === 0 && !canEdit) return null;
  // A dismissed storage prompt is "never mind", not a failure to report.
  const uploadFailed = upload.isError && !(upload.error instanceof UploadCanceledError);

  return (
    <section
      className={
        "mt-6 border-t border-subtle pt-4 " +
        (dragOver ? "rounded-md outline-2 outline-dashed outline-focus/60" : "")
      }
      onDragOver={(event) => {
        if (canEdit) {
          event.preventDefault();
          setDragOver(true);
        }
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
    >
      <div className="mb-3 flex items-center gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
          Attachments{list.length > 0 && ` (${list.length})`}
        </h3>
        {canEdit && (
          <>
            <Button
              variant="secondary"
              size="sm"
              className="ml-auto"
              onClick={() => inputRef.current?.click()}
            >
              <Upload size={11} aria-hidden />
              Upload
            </Button>
            <input
              ref={inputRef}
              type="file"
              multiple
              hidden
              onChange={(event) => {
                uploadAll([...(event.target.files ?? [])]);
                event.target.value = "";
              }}
            />
          </>
        )}
      </div>

      {uploadFailed && (
        <p className="mb-2 text-xs text-red-400">Upload failed: {errorMessage(upload.error)}</p>
      )}
      {upload.isPending && <p className="mb-2 text-xs text-fg-muted">Uploading…</p>}

      {list.length === 0 ? (
        <p className="text-xs text-fg-faint">
          No attachments. {canEdit && "Drop files here, or paste images into the description."}
        </p>
      ) : (
        <ul className="flex flex-wrap gap-2.5">
          {list.map((attachment) => (
            <AttachmentCard
              key={attachment.id}
              attachment={attachment}
              canEdit={canEdit}
              onDelete={() => remove.mutate(attachment.id)}
              onLock={() => setAclTarget(attachment)}
            />
          ))}
        </ul>
      )}

      {aclTarget && (
        <Modal title={`Access — ${aclTarget.filename}`} onClose={() => setAclTarget(null)}>
          <AccessGrantsEditor
            resourceType="attachment"
            resourceId={aclTarget.id}
            accesses={["read"]}
            description="No grants = everyone who can see this item. Any grant restricts the file to the people listed (the uploader always keeps access)."
          />
        </Modal>
      )}
    </section>
  );
}

function AttachmentCard({
  attachment,
  canEdit,
  onDelete,
  onLock,
}: {
  attachment: Attachment;
  canEdit: boolean;
  onDelete: () => void;
  onLock: () => void;
}) {
  const url = attachmentUrl(attachment.id);
  return (
    <li className="group/att relative">
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        title={`${attachment.filename} · ${formatSize(attachment.size_bytes)}${attachment.storage_host_name ? ` · stored on ${attachment.storage_host_name}` : ""}`}
        className="block overflow-hidden rounded-md border border-subtle bg-surface hover:border-emphasis"
      >
        {isInlineImage(attachment) ? (
          <img
            src={url}
            alt={attachment.filename}
            loading="lazy"
            className="size-24 object-cover"
          />
        ) : (
          <span className="flex size-24 flex-col items-center justify-center gap-1.5 px-2 text-fg-muted">
            <FileText size={20} aria-hidden />
            <span className="w-full truncate text-center text-[10px]">
              {attachment.filename}
            </span>
            <span className="text-[9px] text-fg-faint">
              {formatSize(attachment.size_bytes)}
              {attachment.storage_host_name ? ` · ${attachment.storage_host_name}` : ""}
            </span>
          </span>
        )}
      </a>
      {/* Lock affordance (spec 102 ACL): restricted files always show a filled
          accent lock; open files reveal an outline lock on hover. Editors click
          through to the grants editor; readers just see the state. */}
      {canEdit ? (
        <button
          type="button"
          onClick={onLock}
          aria-label={`Manage access to ${attachment.filename}`}
          title={
            attachment.restricted
              ? "Access restricted — manage who can read this file"
              : "Restrict who can read this file"
          }
          className={
            "absolute -left-1.5 -top-1.5 rounded-full border p-0.5 cursor-pointer " +
            (attachment.restricted
              ? "border-transparent bg-accent text-white hover:bg-accent-hover"
              : "hidden border-emphasis bg-elevated text-fg-secondary hover:text-fg group-hover/att:block")
          }
        >
          {attachment.restricted ? (
            <Lock size={11} aria-hidden />
          ) : (
            <LockOpen size={11} aria-hidden />
          )}
        </button>
      ) : (
        attachment.restricted && (
          <span
            title="Access to this file is restricted"
            className="absolute -left-1.5 -top-1.5 rounded-full bg-accent p-0.5 text-white"
          >
            <Lock size={11} aria-hidden />
          </span>
        )
      )}
      {canEdit && (
        <button
          type="button"
          onClick={onDelete}
          aria-label={`Delete ${attachment.filename}`}
          title="Delete attachment"
          className="absolute -right-1.5 -top-1.5 hidden rounded-full border border-emphasis bg-elevated p-0.5 text-fg-secondary hover:text-red-300 group-hover/att:block cursor-pointer"
        >
          <X size={11} aria-hidden />
        </button>
      )}
    </li>
  );
}
