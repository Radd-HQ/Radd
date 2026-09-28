import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderInput, X } from "lucide-react";
import { Entity, ErrorText, invalidateEntities } from "@radd/plugin-sdk";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { BULK_SKIP_REASON_LABELS } from "../../lib/meta";
import { pushToast, ToastKind } from "../../lib/toast";
import {
  ItemKind,
  type BulkSkipped,
  type BulkUpdateResult,
  type Item,
  type ItemBulkPatch,
  type ItemLinkSearchResult,
} from "../../lib/types";
import { Button, ButtonSize, ButtonVariant } from "../Button";
import { Modal } from "../Modal";
import { ParentSearchInput } from "./ParentPicker";
import type { Project } from "@radd-plugin-ui/projects/types";

const plural = (count: number, noun: string) => `${count} ${noun}${count === 1 ? "" : "s"}`;

/**
 * RADD-1473: an epic adopts issues that already exist. Epics only — an issue's subtask checklist
 * has no such action, because a subtask cannot exist without a parent and so there is never an
 * existing one to add. The button opens the modal; the modal does the work.
 */
export function AddExistingChildren({ epic, project }: { epic: Item; project: Project }) {
  const [open, setOpen] = useState(false);
  if (epic.kind !== ItemKind.epic) return null;
  return (
    <>
      <Button
        variant={ButtonVariant.ghost}
        size={ButtonSize.sm}
        className="mt-1 self-start"
        onClick={() => setOpen(true)}
      >
        <FolderInput size={13} aria-hidden />
        Add existing…
      </Button>
      {open && <AddExistingChildrenModal epic={epic} project={project} onClose={() => setOpen(false)} />}
    </>
  );
}

/**
 * Pick any number of issues that have no epic yet (the typeahead asks the server for exactly those),
 * then ONE bulk update sets `parent_id` for all of them (RADD-1474). The children list refreshes
 * through the item entity tag; rows the server refused stay picked and are listed with the reason,
 * so a second try is one click, not a second search.
 */
function AddExistingChildrenModal({
  epic,
  project,
  onClose,
}: {
  epic: Item;
  project: Project;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<ItemLinkSearchResult[]>([]);
  const [skipped, setSkipped] = useState<BulkSkipped[]>([]);
  const excludeIds = useMemo(
    () => new Set([epic.id, ...picked.map((candidate) => candidate.id)]),
    [epic.id, picked],
  );

  const add = useMutation({
    mutationFn: () => {
      const patch: ItemBulkPatch = { parent_id: epic.id };
      return api.post<BulkUpdateResult>(ApiPath.itemsBulkUpdate, {
        item_ids: picked.map((candidate) => candidate.id),
        patch,
      });
    },
    onSuccess: (result) => {
      void invalidateEntities(queryClient, Entity.item);
      if (result.updated.length > 0) {
        pushToast(`Added ${plural(result.updated.length, "issue")} to ${epic.key}`, ToastKind.success);
      }
      if (result.skipped.length === 0) {
        onClose();
        return;
      }
      const refused = new Set(result.skipped.map((row) => row.item_id));
      setSkipped(result.skipped);
      setPicked((current) => current.filter((candidate) => refused.has(candidate.id)));
    },
  });

  const remove = (id: string) => setPicked((current) => current.filter((candidate) => candidate.id !== id));

  return (
    <Modal title={`Add existing issues to ${epic.key}`} onClose={onClose}>
      <div className="space-y-4" data-add-existing-children>
        <p className="text-xs leading-relaxed text-fg-secondary">
          Issues that have no epic yet — this project's own first. Each one you pick becomes a
          child of this epic.
        </p>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="add-existing-search" className="text-xs font-medium text-fg-secondary">
            Issues
          </label>
          {picked.length > 0 && (
            <ul className="flex items-center gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" aria-label="Picked issues">
              {picked.map((candidate) => (
                <li
                  key={candidate.id}
                  data-picked-child={candidate.key}
                  className="inline-flex shrink-0 items-center gap-1 rounded border border-subtle bg-elevated py-px pl-1.5 pr-0.5 text-[11px] leading-4 text-fg"
                >
                  <span className="font-mono text-fg-muted">{candidate.key}</span>
                  <span className="max-w-40 truncate">{candidate.title}</span>
                  <button
                    type="button"
                    aria-label={`Remove ${candidate.key}`}
                    onClick={() => remove(candidate.id)}
                    className="shrink-0 rounded text-fg-muted hover:text-status-danger-ink cursor-pointer"
                  >
                    <X size={11} aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <ParentSearchInput
            id="add-existing-search"
            projectId={project.id}
            kind={ItemKind.issue}
            unparented
            excludeIds={excludeIds}
            autoFocus
            placeholder="Search issues without an epic…"
            onPick={(candidate) => setPicked((current) => [...current, candidate])}
          />
        </div>
        {skipped.length > 0 && (
          <ul role="alert" className="space-y-1 text-xs text-status-danger-ink" data-add-existing-skipped>
            {skipped.map((row) => (
              <li key={row.item_id}>
                <span className="font-mono">{row.key ?? row.item_id}</span>
                {": "}
                {row.detail ?? BULK_SKIP_REASON_LABELS[row.reason] ?? row.reason}
              </li>
            ))}
          </ul>
        )}
        {add.isError && <ErrorText error={add.error} />}
        <div className="flex justify-end gap-2">
          <Button variant={ButtonVariant.ghost} onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={picked.length === 0 || add.isPending} onClick={() => add.mutate()}>
            {add.isPending ? "Adding…" : `Add ${plural(picked.length, "issue")}`}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
