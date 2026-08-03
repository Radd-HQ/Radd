/** Attachments (spec 29; polymorphic parents — item or pages page). */
// ---------------------------------------------------------------------------
// Attachments (attachments module — spec 29)
// ---------------------------------------------------------------------------

/** What an attachment can be parented to. Values are the server's entity keys —
 *  `AttachmentParentType` in `attachments/types.py`, which the upload endpoint
 *  validates as an enum. RADD-701 renamed this key from `docPage` to `page` and
 *  left the VALUE at `doc_page`, so every page upload 422'd for a day (RADD-761). */
export const AttachmentParentType = {
  item: "item",
  page: "page",
} as const;
export type AttachmentParentTypeValue =
  (typeof AttachmentParentType)[keyof typeof AttachmentParentType];

/** The parent an upload/list addresses on the canonical /attachments API. */
export interface AttachmentTarget {
  entityType: AttachmentParentTypeValue;
  entityId: string;
}

export interface Attachment {
  id: string;
  /** Legacy mirror of entity_id for item parents; null otherwise — read entity_id. */
  item_id: string | null;
  entity_type: AttachmentParentTypeValue;
  entity_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_by: string | null;
  created_at: string;
  /** Any spec-92 read grants exist → the lock badge (spec 102 ACL). */
  restricted: boolean;
  /** Storage host holding the bytes (spec 102) — "" on older responses. */
  storage_host_name: string;
}
