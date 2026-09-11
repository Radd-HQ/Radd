import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { queryKeys } from "../../lib/queries";
import { managedFieldQuery, type ManagedField } from "../../lib/queries/field-settings";
import { FIELD_TYPE_LABELS } from "../../lib/meta";
import { Button } from "../Button";
import { IconButton } from "../IconButton";
import { useConfirm } from "../ConfirmDialog";
import { TableSkeleton } from "../TableSkeleton";
import { QueryError } from "../QueryError";
import { ErrorText } from "../ErrorText";
import { FieldScopeEditor } from "./FieldScopeEditor";
import { FieldDefaultEditor } from "./FieldDefaultEditor";
import { FieldOptionsSection } from "./FieldOptionsSection";
import { AccessGrantsEditor } from "./AccessGrantsEditor";

export function FieldEditor({ id, allowGlobal, onDeleted }: { id: string; allowGlobal: boolean; onDeleted: () => void }) {
  const field = useQuery(managedFieldQuery(id));
  return <section aria-label="Field definition" className="min-w-0">
    {field.isPending ? <TableSkeleton rows={3} /> : field.isError ? <div><QueryError label="field definition" error={field.error} /><Button variant="secondary" onClick={() => void field.refetch()}>Retry field</Button></div>
      : <FieldDetail key={id} field={field.data} allowGlobal={allowGlobal} onDeleted={onDeleted} />}
  </section>;
}

/** The right pane: everything editable about one field. */
function FieldDetail({
  field,
  allowGlobal,
  onDeleted,
}: {
  field: ManagedField;
  allowGlobal: boolean;
  onDeleted: () => void;
}) {
  const queryClient = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const del = useMutation({
    mutationFn: () => api.delete(`${ApiPath.fields}/${field.id}`),
    onSuccess: async () => {
      const deletedKey = managedFieldQuery(field.id).queryKey;
      await queryClient.cancelQueries({ queryKey: deletedKey });
      // Refresh the rail before choosing its next field. The deleted definition
      // is still mounted during that refresh and must not be fetched again.
      await queryClient.invalidateQueries({
        queryKey: queryKeys.fields,
        predicate: query => JSON.stringify(query.queryKey.slice(0, deletedKey.length)) !== JSON.stringify(deletedKey),
      });
      onDeleted();
      queryClient.removeQueries({ queryKey: deletedKey });
    },
  });

  return (
    <div className="rounded-lg border border-subtle">
      <div className="flex items-start justify-between gap-3 border-b border-subtle/60 px-4 py-3">
        <div>
          <h4 className="text-sm font-semibold text-heading">{field.name}</h4>
          <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-fg-muted">
            <span className="rounded bg-elevated px-1 font-mono">{field.key}</span>
            <span>{FIELD_TYPE_LABELS[field.type]}</span>
            {field.required && <span className="text-status-warning-ink">required</span>}
          </p>
        </div>
        {field.can_delete && (
          <IconButton
            aria-label="Delete field"
            danger
            disabled={del.isPending}
            onClick={() =>
              void confirm({
                title: "Delete field",
                message: `Delete the "${field.name}" field? Its values stay on items but stop rendering.`,
                confirmLabel: "Delete",
                danger: true,
              }).then((ok) => {
                if (ok) del.mutate();
              })
            }
            className="flex size-8 shrink-0 items-center justify-center"
          >
            <Trash2 size={14} aria-hidden />
          </IconButton>
        )}
      </div>

      <dl className="flex flex-col divide-y divide-subtle/60">
        {/* RADD-822: two mechanisms both said "project". Named for their
            questions now — "Available on" (does the field EXIST here) vs
            "Restricted on" (who may read/write it, per project). */}
        <Row label="Available on">
          <FieldScopeEditor field={field} allowGlobal={allowGlobal || field.project_ids.length === 0} canManage={field.can_update} />
        </Row>

        {(field.type === "select" || field.type === "multi_select") && (
          <Row label="Options">
            <FieldOptionsSection field={field} canManage={field.can_update} />
          </Row>
        )}

        <Row label="Default">
          <FieldDefaultEditor field={field} canManage={field.can_update} />
        </Row>


        <Row label="Restricted on" full>
          {field.can_manage ? <AccessGrantsEditor resourceType="field" resourceId={field.id} /> : <p className="text-xs text-fg-muted">Managing grants requires field management permission over the whole field scope.</p>}
        </Row>
      </dl>
      {del.isError && (
        <ErrorText className="px-4 py-2" error={del.error} />
      )}
      {confirmDialog}
    </div>
  );
}

/** A labelled row in the detail pane. `full` drops the two-column layout for wide editors. */
function Row({
  label,
  children,
  full = false,
}: {
  label: string;
  children: React.ReactNode;
  full?: boolean;
}) {
  if (full) {
    return (
      <div className="px-4 py-3">
        <p className="mb-2 text-xs font-medium text-fg-secondary">{label}</p>
        {children}
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-[100px_minmax(0,1fr)] items-start gap-3 px-4 py-3">
      <dt className="pt-1 text-xs font-medium text-fg-secondary">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
