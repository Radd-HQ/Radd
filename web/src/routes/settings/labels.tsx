import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Tags } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { labelsQuery, queryKeys } from "../../lib/queries";
import { Permission, type Label, type LabelCreate } from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { QueryError } from "../../components/QueryError";

/** Default swatch offered by the color input for a fresh label. */
const DEFAULT_LABEL_COLOR = "#6366f1";
/** Swatch shown for labels created without a color (auto-created on first use). */
const NO_COLOR_SWATCH_CLASS = "bg-strong";

export function LabelsSettingsPage() {
  const perms = usePermissions();
  // Label creation requires project.manage at global scope (backend rule).
  const canManage = perms.global(Permission.labelManage);
  const labels = useQuery(labelsQuery());
  const list = labels.data ?? [];

  return (
    <SettingsPage
      title="Labels"
      description="Global labels. Items also auto-create labels on first use; rename/delete isn't supported by the API yet."
    >
      {labels.isPending ? (
        <TableSkeleton rows={4} />
      ) : labels.isError ? (
        <QueryError label="labels" error={labels.error} />
      ) : (
        <>
          {list.length === 0 ? (
            <EmptyState icon={Tags} message="No labels yet — create one below or add one to an item." />
          ) : (
            <ul className="rounded-lg border border-subtle">
              {list.map((label) => (
                <li
                  key={label.id}
                  className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5 last:border-b-0"
                >
                  {label.color ? (
                    <span
                      className="size-3 shrink-0 rounded-full"
                      style={{ backgroundColor: label.color }}
                      aria-hidden
                    />
                  ) : (
                    <span
                      className={`size-3 shrink-0 rounded-full ${NO_COLOR_SWATCH_CLASS}`}
                      aria-hidden
                    />
                  )}
                  <span className="flex-1 text-[13px] text-heading">{label.name}</span>
                  <span className="font-mono text-[11px] text-fg-faint">{label.color ?? "—"}</span>
                  <span className="text-xs text-fg-faint">
                    {new Date(label.created_at).toLocaleDateString()}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {canManage && <AddLabelForm />}
        </>
      )}
    </SettingsPage>
  );
}

function AddLabelForm() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [color, setColor] = useState(DEFAULT_LABEL_COLOR);

  const createLabel = useMutation({
    mutationFn: (body: LabelCreate) => api.post<Label>(ApiPath.labels, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.labels });
      setName("");
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    createLabel.mutate({ name: name.trim(), color });
  };

  return (
    <form onSubmit={onSubmit} className="mt-4 flex items-end gap-3">
      <div className="flex-1">
        <TextField
          label="New label"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="regression"
          maxLength={100}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor="label-color" className="text-xs font-medium text-fg-secondary">
          Color
        </label>
        <input
          id="label-color"
          type="color"
          value={color}
          onChange={(event) => setColor(event.target.value)}
          className="h-8 w-12 cursor-pointer rounded-md border border-strong bg-surface p-1"
        />
      </div>
      <Button type="submit" disabled={createLabel.isPending || !name.trim()}>
        <Plus size={14} aria-hidden />
        {createLabel.isPending ? "Creating…" : "Create label"}
      </Button>
      {createLabel.isError && (
        <span className="pb-2 text-xs text-red-400">{errorMessage(createLabel.error)}</span>
      )}
    </form>
  );
}
