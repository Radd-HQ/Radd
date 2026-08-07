import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Plus, Tags, Trash2, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { useListFilter } from "../../lib/list-filter";
import { labelsQuery, queryKeys } from "../../lib/queries";
import { Permission, type Label, type LabelCreate } from "../../lib/types";
import { Button } from "../../components/Button";
import { useConfirm } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { IconButton } from "../../components/IconButton";
import { ListSearchInput } from "../../components/ListSearchInput";
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
  const canManage = perms.global(Permission.labelUpdate);
  // RADD-950: a separate atom, and a separate control. Someone who may tidy a
  // name is not necessarily someone who may strip a label off every issue.
  const canDelete = perms.global(Permission.labelDelete);
  const labels = useQuery(labelsQuery());
  const all = labels.data ?? [];
  const search = useListFilter(all, (label) => [label.name]);
  const list = search.filtered;
  const [confirmDialog, confirm] = useConfirm();

  return (
    <SettingsPage
      title="Labels"
      description="Global labels, shared by issues and pages. Items also auto-create one on first use, which is why this list grows on its own."
    >
      {labels.isPending ? (
        <TableSkeleton rows={4} />
      ) : labels.isError ? (
        <QueryError label="labels" error={labels.error} />
      ) : (
        <>
          {all.length === 0 ? (
            <EmptyState icon={Tags} message="No labels yet — create one below or add one to an item." />
          ) : (
            <>
              {all.length > 8 && (
                <ListSearchInput
                  className="mb-3"
                  value={search.filter}
                  onChange={search.setFilter}
                  placeholder="Filter labels by name…"
                  total={all.length}
                  matched={list.length}
                  noun="labels"
                />
              )}
              {list.length === 0 ? (
                <EmptyState icon={Tags} message={`No labels match “${search.filter.trim()}”.`} />
              ) : (
                <ul className="rounded-lg border border-subtle">
                  {list.map((label) => (
                    <LabelRow
                      key={label.id}
                      label={label}
                      canManage={canManage}
                      canDelete={canDelete}
                      confirm={confirm}
                    />
                  ))}
                </ul>
              )}
            </>
          )}
          {canManage && <AddLabelForm />}
        </>
      )}
      {confirmDialog}
    </SettingsPage>
  );
}

/** One label: swatch, name, colour, created — plus rename and delete for
 *  whoever holds the atoms (RADD-950; both endpoints have existed since spec 87
 *  and this page used to claim otherwise). */
function LabelRow({
  label,
  canManage,
  canDelete,
  confirm,
}: {
  label: Label;
  canManage: boolean;
  canDelete: boolean;
  confirm: ReturnType<typeof useConfirm>[1];
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(label.name);
  const [color, setColor] = useState(label.color ?? DEFAULT_LABEL_COLOR);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.labels });
  const save = useMutation({
    mutationFn: (body: { name: string; color: string }) =>
      api.patch<Label>(`${ApiPath.labels}/${label.id}`, body),
    onSuccess: async () => {
      await invalidate();
      setEditing(false);
    },
  });
  const remove = useMutation({
    mutationFn: () => api.delete<void>(`${ApiPath.labels}/${label.id}`),
    onSuccess: invalidate,
  });

  const commit = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    if (trimmed === label.name && color === (label.color ?? DEFAULT_LABEL_COLOR)) {
      setEditing(false);
      return;
    }
    save.mutate({ name: trimmed, color });
  };

  return (
    <li className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5 last:border-b-0">
      {editing ? (
        <>
          <input
            type="color"
            value={color}
            onChange={(event) => setColor(event.target.value)}
            aria-label={`Colour for ${label.name}`}
            className="h-6 w-8 shrink-0 cursor-pointer rounded border border-strong bg-surface p-0.5"
          />
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") commit();
              if (event.key === "Escape") setEditing(false);
            }}
            aria-label={`Rename ${label.name}`}
            maxLength={100}
            autoFocus
            className="h-7 flex-1 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading focus:outline-2 focus:outline-offset-1 focus:outline-focus"
          />
          <IconButton onClick={commit} disabled={save.isPending} aria-label="Save label">
            <Check size={13} />
          </IconButton>
          <IconButton onClick={() => setEditing(false)} aria-label="Cancel rename">
            <X size={13} />
          </IconButton>
        </>
      ) : (
        <>
          <span
            className={`size-3 shrink-0 rounded-full ${label.color ? "" : NO_COLOR_SWATCH_CLASS}`}
            style={label.color ? { backgroundColor: label.color } : undefined}
            aria-hidden
          />
          <span className="flex-1 text-[13px] text-heading">{label.name}</span>
          <span className="font-mono text-[11px] text-fg-faint">{label.color ?? "—"}</span>
          <span className="text-xs text-fg-faint">
            {new Date(label.created_at).toLocaleDateString()}
          </span>
          {canManage && (
            <IconButton onClick={() => setEditing(true)} aria-label={`Edit ${label.name}`}>
              <Pencil size={13} />
            </IconButton>
          )}
          {canDelete && (
            <IconButton
              danger
              disabled={remove.isPending}
              aria-label={`Delete ${label.name}`}
              onClick={() =>
                void confirm({
                  title: `Delete "${label.name}"`,
                  // No count: `labels` deliberately does not read the items
                  // module's tables, and reaching across that seam to decorate
                  // a dialog is not worth the coupling.
                  message:
                    `Remove "${label.name}" from every issue and page that carries it, ` +
                    "and delete the label. This cannot be undone.",
                  confirmLabel: "Delete label",
                  danger: true,
                }).then((ok) => {
                  if (ok) remove.mutate();
                })
              }
            >
              <Trash2 size={13} />
            </IconButton>
          )}
        </>
      )}
      {(save.isError || remove.isError) && (
        <span className="text-xs text-red-400">
          {errorMessage(save.isError ? save.error : remove.error)}
        </span>
      )}
    </li>
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
