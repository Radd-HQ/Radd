import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Tags } from "lucide-react";
import { api } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { apiPageLabelsPath } from "../../lib/constants";
import { labelsQuery } from "../../lib/queries";
import { TokenMultiSelect } from "../TokenMultiSelect";

/**
 * A page's labels (RADD-718) — the cross-cutting axis the tree cannot express.
 *
 * Shares the `labels` vocabulary with issues on purpose: "incident" meaning one
 * thing on an issue and another on a page is how a tag set rots.
 *
 * Read-only for someone without write access — the codebase's rule is to
 * disable up front rather than let an edit fail on save.
 */
export function PageLabels({
  pageId,
  labels,
  canWrite,
}: {
  pageId: string;
  labels: string[];
  canWrite: boolean;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(labels);
  const [editing, setEditing] = useState(false);
  const { data: known } = useQuery({ ...labelsQuery(), enabled: editing });

  // A concurrent edit (or a save) re-seeds the draft.
  useEffect(() => setDraft(labels), [labels]);

  const save = useMutation({
    mutationFn: (next: string[]) => api.put<string[]>(apiPageLabelsPath(pageId), { labels: next }),
    onSettled: () => void invalidateEntities(queryClient, Entity.page),
  });

  if (!editing) {
    if (!labels.length && !canWrite) return null;
    return (
      <div className="mt-2 flex flex-wrap items-center gap-1.5 px-1.5">
        <Tags size={12} aria-hidden className="text-fg-faint" />
        {labels.map((label) => (
          <span
            key={label}
            className="rounded bg-elevated px-1.5 py-px text-[11px] text-fg-secondary"
          >
            {label}
          </span>
        ))}
        {canWrite && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="rounded px-1 text-[11px] text-fg-faint hover:text-fg cursor-pointer"
          >
            {labels.length ? "Edit" : "Add labels"}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="mt-2 flex items-center gap-2 px-1.5">
      <TokenMultiSelect
        value={draft}
        onChange={setDraft}
        options={(known ?? []).map((label) => ({ value: label.name, label: label.name }))}
        allowCreate
        ariaLabel="Page labels"
        placeholder="Label…"
      />
      <button
        type="button"
        onClick={() => {
          save.mutate(draft);
          setEditing(false);
        }}
        className="rounded px-1.5 text-[11px] text-accent-text hover:underline cursor-pointer"
      >
        Done
      </button>
    </div>
  );
}
