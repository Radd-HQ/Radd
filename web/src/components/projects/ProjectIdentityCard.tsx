import { useId, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderKanban } from "lucide-react";
import { api } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { apiProjectPath } from "../../lib/constants";
import { pushToast, ToastKind } from "../../lib/toast";
import type { Project, ProjectUpdate } from "../../lib/types";
import { Button } from "../Button";
import { ErrorText } from "../ErrorText";
import { TextField } from "../TextField";

/**
 * Name + description (RADD-1009) — the first card on Settings → Project →
 * General. The KEY is displayed but not editable: item keys derive from it.
 * Saving invalidates every project query, so the settings header, the
 * sidebar rail and the projects index re-render with the new name at once.
 */
export function ProjectIdentityCard({ project, canManage }: { project: Project; canManage: boolean }) {
  const queryClient = useQueryClient();
  const descriptionId = useId();
  // Keyed on the project by the caller, so a route change resets the drafts.
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);

  const save = useMutation({
    mutationFn: (body: ProjectUpdate) => api.patch<Project>(apiProjectPath(project.id), body),
    onSuccess: async (saved) => {
      setName(saved.name);
      setDescription(saved.description);
      await invalidateEntities(queryClient, Entity.project);
      pushToast("Project saved.", ToastKind.success);
    },
  });

  const dirty = name.trim() !== project.name || description !== project.description;
  const disabled = !canManage || save.isPending;
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || !dirty) return;
    const body: ProjectUpdate = {};
    if (name.trim() !== project.name) body.name = name.trim();
    if (description !== project.description) body.description = description;
    save.mutate(body);
  };

  return (
    <section data-project-identity className="rounded-lg border border-subtle bg-surface p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-heading">
        <FolderKanban size={15} aria-hidden className="text-fg-muted" />
        Name and description
      </h2>
      <p className="mt-1 text-xs text-fg-secondary">
        The key <span className="rounded bg-elevated px-1 py-0.5 font-mono text-[11px] text-fg">{project.key}</span>{" "}
        cannot change — every issue key derives from it.
      </p>
      <form onSubmit={onSubmit} className="mt-3 flex flex-col gap-3">
        <TextField
          label="Name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={200}
          required
          disabled={disabled}
        />
        <div className="flex flex-col gap-1.5">
          <label htmlFor={descriptionId} className="text-xs font-medium text-fg-secondary">
            Description
          </label>
          <textarea
            id={descriptionId}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            rows={3}
            maxLength={4000}
            disabled={disabled}
            placeholder="What this project is for, in a sentence or two."
            className="rounded-md border border-subtle bg-surface px-2.5 py-2 text-[13px] text-heading placeholder:text-fg-faint focus:outline-none focus:ring-2 focus:border-accent focus:ring-accent/30 disabled:cursor-not-allowed disabled:opacity-70"
          />
          <p className="text-xs text-fg-muted">Shown under the name on the projects index and in this header.</p>
        </div>
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={disabled || !dirty || !name.trim()}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
          {save.isError && <ErrorText error={save.error} />}
        </div>
      </form>
    </section>
  );
}
