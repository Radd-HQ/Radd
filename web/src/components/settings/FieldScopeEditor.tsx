import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { queryKeys } from "../../lib/queries";
import type { FieldDef, Project } from "../../lib/types";
import { ScopePicker } from "./ScopePicker";

/**
 * Edit a field's SCOPE (spec 90 follow-up): global (every project) or scoped to a
 * set of projects, via the shared ScopePicker. Each add/remove PATCHes `project_ids`
 * immediately — scope can be widened later (add a project) or promoted to global
 * (clear the selection).
 */
export function FieldScopeEditor({
  field,
  projects,
  canManage,
}: {
  field: FieldDef;
  projects: Project[];
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: (project_ids: string[]) =>
      api.patch(`${ApiPath.fields}/${field.id}`, { project_ids }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.fields }),
  });

  return (
    <div>
      <ScopePicker
        value={field.project_ids}
        onChange={(ids) => save.mutate(ids)}
        projects={projects}
        disabled={!canManage || save.isPending}
      />
      <p className="mt-1.5 text-[11px] text-fg-faint">
        {field.project_ids.length === 0
          ? "Applies to items in every project."
          : "Applies only to the selected projects — add more, or go Global."}
      </p>
      {save.isError && <p className="text-[11px] text-red-400">{errorMessage(save.error)}</p>}
    </div>
  );
}
