import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, ChevronUp, FileText, Plus, Shapes, Star, Trash2 } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { issueTypesQuery, projectByIdQuery, queryKeys } from "../../lib/queries";
import { Permission, type IssueType } from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { ValueChip } from "../../components/items/ValueChip";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { QueryError } from "../../components/QueryError";
import { IconButton } from "../../components/IconButton";

const PALETTE = ["#64748b", "#ef4444", "#f97316", "#eab308", "#22c55e", "#3b82f6", "#a855f7", "#ec4899"];

/** Per-project issue types admin (spec 51). Reached at /p/$key/settings/types. */
export function IssueTypesSettingsPage({ projectId }: { projectId?: string }) {
  const perms = usePermissions();
  const projectQuery = useQuery(projectByIdQuery(projectId ?? ""));
  const project = projectQuery.data;
  const canManage = perms.project(project, Permission.projectManage);
  const types = useQuery({ ...issueTypesQuery(projectId ?? ""), enabled: Boolean(projectId) });
  const queryClient = useQueryClient();
  const sorted = [...(types.data ?? [])].sort((a, b) => a.position - b.position);

  // Swap a type's position with its neighbour (two PATCHes), then refresh.
  const move = async (index: number, direction: -1 | 1) => {
    const a = sorted[index];
    const b = sorted[index + direction];
    if (!a || !b) return;
    await Promise.all([
      api.patch(`${ApiPath.issueTypes}/${a.id}`, { position: b.position }),
      api.patch(`${ApiPath.issueTypes}/${b.id}`, { position: a.position }),
    ]);
    await queryClient.invalidateQueries({ queryKey: queryKeys.issueTypes(projectId ?? "") });
  };

  return (
    <SettingsPage history={{ entities: ["issue_type"], projectId }}
      title="Issue types"
      description="What an issue is — a Bug, a Task, a Story — shown as a coloured chip on boards, lists and the issue view. Separate from the hierarchy: a Bug can be an epic, an issue or a subtask. New issues get the default type."
    >
      {(projectId && projectQuery.isPending) || (projectId && types.isPending) ? (
        <TableSkeleton rows={5} />
      ) : projectQuery.isError ? (
        <QueryError label="project" error={projectQuery.error} />
      ) : !project ? (
        <EmptyState icon={Shapes} message="Create a project first — issue types live per project." />
      ) : types.isError ? (
        <QueryError label="types" error={types.error} />
      ) : (
        <>
          <ul className="rounded-lg border border-subtle">
            {sorted.map((issueType, index) => (
              <TypeRow
                key={issueType.id}
                issueType={issueType}
                projectId={project.id}
                canManage={canManage}
                onMoveUp={index > 0 ? () => move(index, -1) : undefined}
                onMoveDown={index < sorted.length - 1 ? () => move(index, 1) : undefined}
              />
            ))}
            {sorted.length === 0 && (
              <li className="px-4 py-6 text-center text-sm text-fg-muted">No types yet.</li>
            )}
          </ul>
          {canManage && <AddTypeForm projectId={project.id} />}
        </>
      )}
    </SettingsPage>
  );
}

function TypeRow({
  issueType,
  projectId,
  canManage,
  onMoveUp,
  onMoveDown,
}: {
  issueType: IssueType;
  projectId: string;
  canManage: boolean;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
}) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  // Description template (spec 76): collapsed by default; the textarea PATCHes
  // on Save (a per-keystroke immediate PATCH would spam the API with markdown).
  const [templateOpen, setTemplateOpen] = useState(false);
  const [templateDraft, setTemplateDraft] = useState(issueType.description_template ?? "");
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.issueTypes(projectId) });

  const save = useMutation({
    mutationFn: (body: Partial<IssueType>) =>
      api.patch<IssueType>(`${ApiPath.issueTypes}/${issueType.id}`, body),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => api.delete<void>(`${ApiPath.issueTypes}/${issueType.id}`),
    onSuccess: invalidate,
  });
  const hasTemplate = Boolean(issueType.description_template);
  const templateDirty = templateDraft !== (issueType.description_template ?? "");

  return (
    <li className="border-b border-subtle/60 last:border-b-0">
    <div className="flex items-center gap-3 px-4 py-2.5">
      {canManage && (
        <span className="flex flex-col text-fg-faint">
          <button
            type="button"
            disabled={!onMoveUp}
            onClick={onMoveUp}
            aria-label="Move up"
            className="cursor-pointer hover:text-fg disabled:opacity-30 disabled:cursor-default"
          >
            <ChevronUp size={13} />
          </button>
          <button
            type="button"
            disabled={!onMoveDown}
            onClick={onMoveDown}
            aria-label="Move down"
            className="cursor-pointer hover:text-fg disabled:opacity-30 disabled:cursor-default"
          >
            <ChevronDown size={13} />
          </button>
        </span>
      )}
      <ValueChip label={issueType.name} color={issueType.color} icon={issueType.icon} size={18} />
      <span className="flex-1 text-[13px] text-heading">{issueType.name}</span>
      {issueType.is_default ? (
        <span className="inline-flex items-center gap-1 rounded border border-accent/40 px-1.5 py-px text-[11px] text-accent-text">
          <Star size={10} fill="currentColor" aria-hidden />
          Default
        </span>
      ) : (
        canManage && (
          <button
            type="button"
            onClick={() => save.mutate({ is_default: true })}
            className="text-[11px] text-fg-muted hover:text-accent-text cursor-pointer"
          >
            Make default
          </button>
        )
      )}
      {canManage && (
        <button
          type="button"
          onClick={() => {
            setTemplateDraft(issueType.description_template ?? "");
            setTemplateOpen((current) => !current);
          }}
          aria-expanded={templateOpen}
          title={hasTemplate ? "Edit description template" : "Add a description template"}
          className={
            "flex items-center gap-1 rounded border px-1.5 py-px text-[11px] cursor-pointer " +
            (hasTemplate
              ? "border-accent/40 text-accent-text hover:border-accent-hover"
              : "border-strong text-fg-muted hover:border-emphasis hover:text-fg")
          }
        >
          <FileText size={10} aria-hidden />
          Template
        </button>
      )}
      {canManage && (
        <input
          type="color"
          value={issueType.color}
          aria-label={`${issueType.name} color`}
          onChange={(event) => save.mutate({ color: event.target.value })}
          className="size-6 cursor-pointer rounded border border-strong bg-transparent"
        />
      )}
      {canManage && !issueType.is_default && (
        <IconButton
          danger
          onClick={() => (confirming ? remove.mutate() : setConfirming(true))}
          onBlur={() => setConfirming(false)}
          aria-label={`Delete ${issueType.name}`}
        >
          {confirming ? <Check size={13} className="text-red-400" /> : <Trash2 size={13} />}
        </IconButton>
      )}
      {(save.isError || remove.isError) && (
        <span className="text-[11px] text-red-400">
          {errorMessage(save.error ?? remove.error)}
        </span>
      )}
    </div>

    {/* Description template (spec 76): markdown prefilled into the new-item
        description when this type is selected while the draft is pristine. */}
    {templateOpen && canManage && (
      <div className="flex flex-col gap-2 px-4 pb-3">
        <textarea
          value={templateDraft}
          onChange={(event) => setTemplateDraft(event.target.value)}
          rows={5}
          placeholder={"## Steps to reproduce\n\n## Expected\n\n## Actual"}
          aria-label={`${issueType.name} description template`}
          className="w-full rounded-md border border-strong bg-base px-2.5 py-2 font-mono text-xs text-fg placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
        />
        <div className="flex items-center gap-2">
          <Button
            onClick={() =>
              save.mutate(
                { description_template: templateDraft.trim() === "" ? null : templateDraft },
                { onSuccess: () => setTemplateOpen(false) },
              )
            }
            disabled={save.isPending || !templateDirty}
          >
            {save.isPending ? "Saving…" : "Save template"}
          </Button>
          {hasTemplate && (
            <button
              type="button"
              onClick={() =>
                save.mutate(
                  { description_template: null },
                  { onSuccess: () => setTemplateOpen(false) },
                )
              }
              className="text-xs text-fg-muted hover:text-red-300 cursor-pointer"
            >
              Remove template
            </button>
          )}
          <span className="ml-auto text-[11px] text-fg-faint">
            Markdown — prefilled into new issues of this type.
          </span>
        </div>
      </div>
    )}
    </li>
  );
}

function AddTypeForm({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [color, setColor] = useState(PALETTE[5]);

  const create = useMutation({
    mutationFn: () =>
      api.post<IssueType>(ApiPath.issueTypes, { project_id: projectId, name: name.trim(), color }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.issueTypes(projectId) });
      setName("");
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) create.mutate();
  };

  return (
    <form onSubmit={onSubmit} className="mt-4 flex items-end gap-3">
      <div className="flex-1">
        <TextField
          label="New type"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Bug"
          maxLength={100}
        />
      </div>
      <div className="flex items-center gap-1 pb-1">
        {PALETTE.map((swatch) => (
          <button
            key={swatch}
            type="button"
            aria-label={`Use ${swatch}`}
            onClick={() => setColor(swatch)}
            className={
              "size-5 rounded-full cursor-pointer " +
              (color === swatch ? "ring-2 ring-offset-2 ring-offset-base ring-white" : "")
            }
            style={{ backgroundColor: swatch }}
          />
        ))}
      </div>
      <Button type="submit" disabled={create.isPending || !name.trim()}>
        <Plus size={14} aria-hidden />
        {create.isPending ? "Adding…" : "Add type"}
      </Button>
      {create.isError && (
        <span className="pb-2 text-xs text-red-400">{errorMessage(create.error)}</span>
      )}
    </form>
  );
}
