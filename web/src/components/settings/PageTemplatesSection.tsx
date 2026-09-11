import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LayoutTemplate, Pencil, Plus, Trash2, X } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { pageTemplatesPageQuery, pageTemplateByIdQuery, PAGE_TEMPLATES_PAGE_SIZE } from "../../lib/queries";
import { OptionResource } from "../../lib/queries/options";
import { useDirectory } from "../../lib/useDirectory";
import type { PageTemplate } from "../../lib/types";
import { OptionSelect } from "../DirectoryChoices";
import { Button } from "../Button";
import { IconButton } from "../IconButton";
import { useConfirm } from "../ConfirmDialog";
import { Modal } from "../Modal";
import { DirectoryPager } from "../DirectoryPager";
import { ListSearchInput } from "../ListSearchInput";
import { TableSkeleton } from "../TableSkeleton";
import { TextField } from "../TextField";
import { QueryError } from "../QueryError";
import { ErrorText } from "../ErrorText";

/** The template catalog is bounded; only the open editor downloads markdown. */
export function PageTemplatesSection() {
  const queryClient = useQueryClient();
  const templates = useDirectory("page-templates", PAGE_TEMPLATES_PAGE_SIZE, pageTemplatesPageQuery);
  const [editing, setEditing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [confirmDialog, confirm] = useConfirm();
  const { page, total, isSuccess } = templates;
  useEffect(() => {
    if (isSuccess && page > 0 && page * PAGE_TEMPLATES_PAGE_SIZE >= total)
      templates.setPage(Math.max(0, Math.ceil(total / PAGE_TEMPLATES_PAGE_SIZE) - 1));
  }, [page, total, isSuccess]);
  const remove = useMutation({
    mutationFn: (id: string) => api.delete<void>(`${ApiPath.pageTemplates}/${id}`),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["page-templates"] }),
  });
  return <section className="mt-10" aria-label="Page templates">
    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-sm font-semibold text-heading">Page templates</h2>
      <Button size="sm" variant="secondary" onClick={() => setCreating(true)}><Plus size={12} aria-hidden />New template</Button>
    </div>
    <p className="mb-3 text-xs text-fg-muted">Start recurring pages from a template. Title, date and author placeholders are filled when a page is created; other placeholders remain as prompts.</p>
    <ListSearchInput value={templates.filter} onChange={templates.setFilter} placeholder="Find templates…" total={templates.filter.trim() ? undefined : templates.total} matched={templates.total} noun="templates" />
    <div aria-busy={templates.busy} className="mt-3">
      {templates.isPending ? <TableSkeleton rows={2} /> : templates.isError ? <div className="space-y-2">
        <QueryError label="page templates" error={templates.error} /><Button variant="secondary" onClick={() => void templates.refetch()}>Retry templates</Button>
      </div> : templates.rows.length === 0 ? <p className="flex items-center gap-2 text-xs text-fg-muted"><LayoutTemplate size={13} aria-hidden />{templates.filter.trim() ? "No templates match this search." : "No templates yet."}</p>
        : <ul aria-label="Page templates" className="rounded-lg border border-subtle">{templates.rows.map(template => <li key={template.id} className="border-b border-subtle/60 px-4 py-2.5 last:border-b-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="min-w-0 break-words text-[13px] font-medium text-heading">{template.icon ? `${template.icon} ` : ""}{template.name}</span>
            <span className="min-w-0 break-words text-[11px] text-fg-faint">{template.space_id === null ? "Every space" : template.space_name ?? "Unavailable space"}</span>
            <span className="flex-1" />
            <IconButton aria-label={`Edit ${template.name}`} onClick={() => setEditing(template.id)}><Pencil size={13} aria-hidden /></IconButton>
            <IconButton danger disabled={remove.isPending} aria-label={`Delete ${template.name}`} onClick={() => {
              void confirm({title: "Delete template?", message: `Pages already created from “${template.name}” keep their content; only the template goes.`, confirmLabel: "Delete", danger: true})
                .then(ok => { if (ok) remove.mutate(template.id); });
            }}><Trash2 size={13} aria-hidden /></IconButton>
          </div>
          {template.description && <p className="mt-0.5 break-words text-xs text-fg-muted">{template.description}</p>}
        </li>)}</ul>}
    </div>
    <DirectoryPager {...templates} onPage={templates.setPage} label="page templates" />
    {remove.isError && <ErrorText className="mt-2" error={remove.error} />}
    {creating && <Modal title="New page template" onClose={() => setCreating(false)}><TemplateForm onDone={() => setCreating(false)} /></Modal>}
    {editing && <TemplateEditor id={editing} onClose={() => setEditing(null)} />}
    {confirmDialog}
  </section>;
}

function TemplateEditor({id, onClose}: {id: string; onClose: () => void}) {
  const template = useQuery(pageTemplateByIdQuery(id));
  return <Modal title="Edit page template" onClose={onClose}>
    {template.isPending ? <TableSkeleton rows={2} /> : template.isError ? <div className="space-y-2">
      <QueryError label="page template" error={template.error} /><Button variant="secondary" onClick={() => void template.refetch()}>Retry template</Button>
    </div> : <TemplateForm key={id} existing={template.data} onDone={onClose} />}
  </Modal>;
}

function TemplateForm({
  existing,
  onDone,
}: {
  existing?: PageTemplate;
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
        <OptionSelect resource={OptionResource.space} label="Available in" value={spaceId} onChange={setSpaceId}
          presets={[{value: "", label: "Every space", hint: ""}]} />
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
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={save.isPending || !name.trim()}>
          {save.isPending ? "Saving…" : existing ? "Save changes" : "Create template"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          <X size={12} aria-hidden />
          Cancel
        </Button>
        {save.isError && <ErrorText error={save.error} />}
      </div>
    </form>
  );
}
