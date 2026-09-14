import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardList, ExternalLink, Pencil, Plus, Trash2, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { RoutePath, apiFormPath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { formsQuery, projectByIdQuery, queryKeys } from "../../lib/queries";
import { Permission, type Form, type FormUpdate } from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { TableSkeleton } from "../../components/TableSkeleton";
import { FormEditor } from "../../components/forms/FormEditor";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { QueryError } from "../../components/QueryError";
import { IconButton } from "../../components/IconButton";

/**
 * Intake forms admin (spec 20/50) — per-project, gated on form.manage. The
 * project comes from the URL context (`projectId`), not an in-page picker.
 */
export function FormsSettingsPage({ projectId }: { projectId?: string }) {
  const perms = usePermissions();
  const projectQuery = useQuery(projectByIdQuery(projectId ?? ""));
  const [editing, setEditing] = useState<{ form: Form | null } | null>(null);

  const project = projectQuery.data;
  const canManage = perms.project(project, Permission.formManage);
  const forms = useQuery({
    ...formsQuery(projectId ?? "", false),
    enabled: Boolean(projectId) && canManage,
  });
  const list = forms.data ?? [];

  if (project && canManage && editing) {
    return (
      <SettingsPage history={{ entities: ["form"], projectId }}
        title={editing.form ? "Edit intake form" : "New intake form"}
        description={`Project ${project.key} — a title plus registry fields the submitter fills in.`}
      >
        <FormEditor
          project={project}
          form={editing.form}
          onDone={() => setEditing(null)}
        />
      </SettingsPage>
    );
  }

  return (
    <SettingsPage history={{ entities: ["form"], projectId }}
      title="Intake forms"
      description="Forms that create a work item from a title + selected registry fields."
      actions={
        canManage && project ? (
          <Button onClick={() => setEditing({ form: null })} className="self-end">
            <Plus size={14} aria-hidden />
            New form
          </Button>
        ) : undefined
      }
    >
      {(projectId && projectQuery.isPending) || (projectId && canManage && forms.isPending) ? (
        <TableSkeleton rows={4} />
      ) : projectQuery.isError ? (
        <QueryError label="project" error={projectQuery.error} />
      ) : !project ? (
        <EmptyState icon={ClipboardList} message="Project not found." />
      ) : !canManage ? (
        <EmptyState
          icon={ClipboardList}
          message="You need the form.manage permission on this project to manage its forms."
        />
      ) : forms.isError ? (
        <QueryError label="forms" error={forms.error} />
      ) : list.length === 0 ? (
        <EmptyState icon={ClipboardList} message="No forms yet — create one to collect intake." />
      ) : (
        <ul className="rounded-lg border border-subtle">
          {list.map((form) => (
            <FormRow
              key={form.id}
              form={form}
              projectId={project.id}
              projectKey={project.key}
              onEdit={() => setEditing({ form })}
            />
          ))}
        </ul>
      )}
    </SettingsPage>
  );
}

function FormRow({
  form,
  projectId,
  projectKey,
  onEdit,
}: {
  form: Form;
  projectId: string;
  projectKey: string;
  onEdit: () => void;
}) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.forms(projectId) });

  const toggle = useMutation({
    mutationFn: () =>
      api.patch<Form>(apiFormPath(form.id), { enabled: !form.enabled } satisfies FormUpdate, { query: { include_shares: "false" } }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiFormPath(form.id)),
    onSuccess: invalidate,
  });

  return (
    <li className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5 last:border-b-0">
      <ClipboardList size={14} className="shrink-0 text-accent-text" aria-hidden />
      <span className="truncate text-[13px] font-medium text-heading">{form.name}</span>
      <span className="text-[11px] text-fg-faint">
        {form.fields.length} field{form.fields.length === 1 ? "" : "s"}
      </span>

      <Link
        to={RoutePath.formSubmit}
        params={{ projectKey, formId: form.id }}
        className="inline-flex items-center gap-1 text-[11px] text-accent-text hover:text-accent-text"
      >
        <ExternalLink size={11} aria-hidden />
        Submit page
      </Link>

      <label className="ml-auto flex shrink-0 cursor-pointer items-center gap-1.5 text-[11px] text-fg-secondary">
        <input
          type="checkbox"
          checked={form.enabled}
          disabled={toggle.isPending}
          onChange={() => toggle.mutate()}
          className="size-3.5 accent-accent"
        />
        {form.enabled ? "Enabled" : "Disabled"}
      </label>

      {confirming ? (
        <span className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
            className="rounded px-1.5 py-0.5 text-xs text-red-400 hover:bg-elevated cursor-pointer disabled:opacity-50"
          >
            {remove.isPending ? "Deleting…" : "Delete"}
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            aria-label="Cancel delete"
            className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
          >
            <X size={13} />
          </button>
        </span>
      ) : (
        <>
          <IconButton
            onClick={onEdit}
            aria-label={`Edit ${form.name}`}
          >
            <Pencil size={13} />
          </IconButton>
          <IconButton
            danger
            onClick={() => setConfirming(true)}
            aria-label={`Delete ${form.name}`}
          >
            <Trash2 size={13} />
          </IconButton>
        </>
      )}
      {(toggle.isError || remove.isError) && (
        <span className="text-xs text-red-400">{errorMessage(toggle.error ?? remove.error)}</span>
      )}
    </li>
  );
}
