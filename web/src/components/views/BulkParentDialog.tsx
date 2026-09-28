import { useState } from "react";
import { X } from "lucide-react";
import { IconButton } from "@radd/plugin-sdk";
import { ItemKind, type Item, type ItemBulkPatch, type ItemKindValue, type ItemLinkSearchResult } from "../../lib/types";
import { Button, ButtonVariant } from "../Button";
import { Modal } from "../Modal";
import { ParentSearchInput, parentLabel, requiredParentKind } from "../items/ParentPicker";

/** What the bar's parent action is for THIS selection (RADD-1474). */
export interface BulkParentAction {
  /** The button's words: "Epic…" for issues, "Parent issue…" for subtasks. */
  label: string;
  /** The kind the picker searches — null when the action is disabled. */
  parentKind: ItemKindValue | null;
  /** Why it is disabled — the same tooltip idiom as a locked field. */
  reason: string | null;
  /** Issues can shed their epic; a subtask can only move. */
  allowClear: boolean;
}

/**
 * Derive the parent action from the selection's kinds. Every selected row must be loaded on the
 * surface (its kind read from the row), and all must share one kind that can have a parent: a
 * mixed selection has no single parent kind, and an epic has none at all.
 */
export function bulkParentAction(selectedIds: ReadonlySet<string>, items: readonly Item[]): BulkParentAction {
  const kindById = new Map(items.map((item) => [item.id, item.kind ?? ItemKind.issue]));
  const kinds = new Set<ItemKindValue | undefined>();
  for (const id of selectedIds) kinds.add(kindById.get(id));
  const disabled = (reason: string): BulkParentAction => ({
    label: "Epic…", parentKind: null, reason, allowClear: false,
  });
  if (kinds.has(undefined)) {
    return disabled("Some selected items are not on this page, so their kind is unknown — the epic can only be set for a loaded selection.");
  }
  if (kinds.size > 1) {
    return disabled("Select only issues, or only subtasks — a mixed selection has no single parent kind.");
  }
  const [kind] = kinds as Set<ItemKindValue>;
  const parentKind = requiredParentKind(kind);
  if (parentKind === null) return disabled("An epic has no parent.");
  return {
    label: `${parentLabel(kind)}…`,
    parentKind,
    reason: null,
    allowClear: kind === ItemKind.issue,
  };
}

/**
 * The bar's "Epic…" / "Parent issue…" dialog: one search over the kind the selection needs, a pick,
 * and ONE bulk patch. `onApply` is the bar's own bulk update, so refusals report through the same
 * skipped summary as every other bulk action.
 */
export function BulkParentDialog({
  count,
  projectId,
  action,
  pending,
  onApply,
  onClose,
}: {
  count: number;
  projectId: string;
  action: BulkParentAction & { parentKind: ItemKindValue };
  pending: boolean;
  onApply: (patch: ItemBulkPatch) => void;
  onClose: () => void;
}) {
  const [pick, setPick] = useState<ItemLinkSearchResult | null>(null);
  const thing = action.parentKind === ItemKind.epic ? "epic" : "parent issue";
  const rows = action.parentKind === ItemKind.epic
    ? `${count} issue${count === 1 ? "" : "s"}`
    : `${count} subtask${count === 1 ? "" : "s"}`;
  return (
    <Modal title={`Set the ${thing} of ${rows}`} onClose={onClose}>
      <div className="space-y-4" data-bulk-parent-dialog>
        <p className="text-xs leading-relaxed text-fg-secondary">
          Every selected row gets the same {thing}. One the server refuses — a parent you cannot
          see, a row you cannot edit — is skipped and reported; the rest still land.
        </p>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="bulk-parent-search" className="text-xs font-medium text-fg-secondary">
            {parentLabel(action.parentKind === ItemKind.epic ? ItemKind.issue : ItemKind.subtask)}
          </label>
          {pick ? (
            <div
              className="flex h-8 items-center gap-2 rounded-md border border-strong bg-surface px-2.5 text-[13px]"
              data-bulk-parent-pick={pick.key}
            >
              <span className="shrink-0 font-mono text-[11px] text-fg-muted">{pick.key}</span>
              <span className="min-w-0 flex-1 truncate text-fg">{pick.title}</span>
              <IconButton aria-label={`Change ${thing}`} onClick={() => setPick(null)} disabled={pending}>
                <X size={13} aria-hidden />
              </IconButton>
            </div>
          ) : (
            <ParentSearchInput
              id="bulk-parent-search"
              projectId={projectId}
              kind={action.parentKind}
              autoFocus
              onPick={setPick}
            />
          )}
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant={ButtonVariant.ghost} onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          {action.allowClear && (
            <Button
              variant={ButtonVariant.secondary}
              disabled={pending}
              onClick={() => onApply({ parent_id: null })}
            >
              Clear epic
            </Button>
          )}
          <Button disabled={!pick || pending} onClick={() => pick && onApply({ parent_id: pick.id })}>
            {pending ? "Applying…" : `Set ${thing}`}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
