import type { AccessGrantDirectoryRow } from "./queries/fields";
import type { ShareLevelValue } from "./types";

export interface LocalShare {
  draftId?: string;
  kind: "user" | "team" | "group";
  subjectId: string;
  subjectName?: string;
  level: ShareLevelValue;
}
export interface SharingDraft {
  changes: Record<string, { original: AccessGrantDirectoryRow; access: ShareLevelValue | null }>;
  additions: LocalShare[];
}
export const emptySharingDraft = (): SharingDraft => ({ changes: {}, additions: [] });
export const sharingEdits = (draft: SharingDraft) => ({
  changes: Object.values(draft.changes).map(({ original, access }) => ({
    id: original.id, expected_access: original.access, expected_effect: original.effect,
    expected_expires_at: original.expires_at, access,
  })),
  additions: draft.additions.map(row => ({ subject_type: row.kind, subject_id: row.subjectId, access: row.level })),
});
export function changeSharingGrant(draft: SharingDraft, row: AccessGrantDirectoryRow, access: ShareLevelValue | null): SharingDraft {
  const changes = { ...draft.changes };
  const original = changes[row.id]?.original ?? row;
  if (access === original.access) delete changes[row.id];
  else changes[row.id] = { original, access };
  return { ...draft, changes };
}
export interface SharedSave<Definition = never> {
  definition?: Definition;
  sharing?: { global_access: ShareLevelValue | null };
  grants?: ReturnType<typeof sharingEdits>;
  transfer_to?: string;
  expected_owner_id: string | null;
  expected_global_access: ShareLevelValue | null;
}
