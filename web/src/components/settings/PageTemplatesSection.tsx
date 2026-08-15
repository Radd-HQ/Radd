import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LayoutTemplate, Pencil, Plus, Trash2, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { pageSpacesQuery } from "../../lib/queries";
import type { PageTemplate } from "../../lib/types";
import { Button } from "../Button";
import { useConfirm } from "../ConfirmDialog";
import { SelectField } from "../SelectField";
import { TableSkeleton } from "../TableSkeleton";
import { TextField } from "../TextField";
import { QueryError } from "../QueryError";

/** Settings → Pages: page-template management (RADD-1100).
 *
 * The backend family (RADD-712) — CRUD routes, `{{title}}/{{date}}/{{author}}`
 * rendering, `PageCreate.template` — shipped with only the `radd:new-from-template`
 * fence as a consumer, which itself needed a template that only curl could
 * create. This is the missing authoring surface. */

const templatesKey = ["page-templates", "all"] as const;

export function PageTemplatesSection() {
  const queryClient = useQueryClient();
  const templates = useQuery({
    queryKey: templatesKey,
    queryFn: () => api.get<PageTemplate[]>(ApiPath.pageTemplates),
  });
  const spaces = useQuery(pageSpacesQuery());
  const [editing, setEditing] = useState<PageTemplate | null>(null);
  const [creating, setCreating] = useState(false);
  const [confirmDialog, confirm] = useConfirm();

  const remove = useMutation({
    mutationFn: (id: string) => api.delete<void>(`${ApiPath.pageTemplates}/${id}`),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["page-templates"] }),
  });

  const spaceName = (id: string | null) =>
    id === null ? "Every space" : (spaces.data?.find((s) => s.id === id)?.name ?? "One space");

  return (
    <section className="mt-10">
      <div className="mb-1 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-heading">Page templates</h2>
        {!creating && (
          <Button size="sm" variant="secondary" onClick={() => setCreating(true)}>
            <Plus size={12} aria-hidden />
            New template
          </Button>
        )}
      </div>
      <p className="mb-3 text-xs text-fg-muted">
        A shape recurring pages start from — the New page button and the
        new-from-template fence offer these. <code className="font-mono">{"{{title}}"}</code>,{" "}
        <code className="font-mono">{"{{date}}"}</code> and{" "}
        <code className="font-mono">{"{{author}}"}</code> are filled in at creation; any other{" "}
        <code className="font-mono">{"{{placeholder}}"}</code> survives as a prompt to the author.
      </p>
      {creating && (
        <TemplateForm
          spaces={spaces.data ?? []}
          onDone={() => setCreating(false)}
        />
      )}
      {templates.isPending ? (
        <TableSkeleton rows={2} />
      ) : templates.isError ? (
        <QueryError label="page templates" error={templates.error} />
      ) : templates.data.length === 0 ? (
        !creating && (
          <p className="flex items-center gap-2 text-xs text-fg-muted">
            <LayoutTemplate size={13} aria-hidden />
            No templates yet.
          </p>
        )
      ) : (
        <ul className="rounded-lg border border-subtle">
          {templates.data.map((template) => (
            <li key={template.id} className="border-b border-subtle/60 px-4 py-2.5 last:border-b-0">
              <div className="flex items-center gap-2">
                <span className="text-[13px] font-medium text-heading">
                  {template.icon ? `${template.icon} ` : ""}
                  {template.name}
                </span>
                <span className="text-[11px] text-fg-faint">{spaceName(template.space_id)}</span>
                <span className="flex-1" />
                <button
                  type="button"
                  onClick={() => setEditing(editing?.id === template.id ? null : template)}
                  aria-label={`Edit ${template.name}`}
                  className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
                >
                  <Pencil size={13} aria-hidden />
                </button>
                <button
                  type="button"
                  onClick={() => {
                    void confirm({
                      title: "Delete template?",
                      message: `Pages already created from “${template.name}” keep their content; only the template goes.`,
                      confirmLabel: "Delete",
                      danger: true,
                    }).then((ok) => {
                      if (ok) remove.mutate(template.id);
                    });
                  }}
                  aria-label={`Delete ${template.name}`}
                  className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-red-300 cursor-pointer"
                >
                  <Trash2 size={13} aria-hidden />
                </button>
              </div>
              {template.description && (
                <p className="mt-0.5 text-xs text-fg-muted">{template.description}</p>
              )}
              {editing?.id === template.id && (
                <TemplateForm
                  existing={template}
                  spaces={spaces.data ?? []}
                  onDone={() => setEditing(null)}
                />
              )}
            </li>
          ))}
        </ul>
      )}
      {remove.isError && (
        <p className="mt-2 text-xs text-red-400">{errorMessage(remove.error)}</p>
      )}
      {confirmDialog}
    </section>
  );
}

function TemplateForm({
  existing,
  spaces,
  onDone,
}: {
  existing?: PageTemplate;
  spaces: { id: string; name: string }[];
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(existing?.name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [spaceId, setSpaceId] = useState(existing?.space_id ?? "");
  const [body, setBody] = useState(existing?.body ?? "");

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        name: name.trim(),
        description: description.trim(),
        body,
        space_id: spaceId || null,
      };
      return existing
        ? api.patch<PageTemplate>(`${ApiPath.pageTemplates}/${existing.id}`, payload)
        : api.post<PageTemplate>(ApiPath.pageTemplates, payload);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["page-templates"] });
      onDone();
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) save.mutate();
  };

  return (
    <form
      onSubmit={onSubmit}
      className="mt-3 mb-1 flex flex-col gap-3 rounded-lg border border-subtle bg-surface/40 p-3"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          label="Name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Meeting notes"
          maxLength={100}
          required
          autoFocus={!existing}
        />
        <SelectField
          label="Available in"
          value={spaceId}
          onChange={(event) => setSpaceId(event.target.value)}
        >
          <option value="">Every space</option>
          {spaces.map((space) => (
            <option key={space.id} value={space.id}>
              {space.name}
            </option>
          ))}
        </SelectField>
      </div>
      <TextField
        label="Description (optional)"
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        placeholder="When to reach for this template"
      />
      <label className="flex flex-col gap-1 text-xs font-medium text-fg-secondary">
        Body (markdown)
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          rows={8}
          spellCheck={false}
          placeholder={"# {{title}}\n\nDate: {{date}} — Owner: {{author}}\n\n## Agenda\n\n- "}
          className="rounded-md border border-strong bg-base px-3 py-2 font-mono text-[12px] leading-relaxed text-fg outline-focus"
        />
      </label>
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" disabled={save.isPending || !name.trim()}>
          {save.isPending ? "Saving…" : existing ? "Save changes" : "Create template"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          <X size={12} aria-hidden />
          Cancel
        </Button>
        {save.isError && <span className="text-xs text-red-400">{errorMessage(save.error)}</span>}
      </div>
    </form>
  );
}
