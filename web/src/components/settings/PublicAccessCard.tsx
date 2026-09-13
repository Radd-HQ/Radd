import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Globe, UserRoundPlus } from "lucide-react";
import { api } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { apiProjectPublicAccessPath } from "../../lib/constants";
import { pushToast } from "../../lib/toast";
import type { Project, PublicAccessUpdate } from "../../lib/types";

/**
 * Spec 121 — the two public-access switches, a PRESENTATION of two role grants:
 * "Public project" = the Public role granted to Anyone on this project;
 * "contributions" = the Contributor role granted to Signed-in users. The rows
 * themselves appear in the grants table below and in the inspector; flipping a
 * switch here and revoking the row there are the same act.
 */
export function PublicAccessCard({ project, canManage }: { project: Project; canManage: boolean }) {
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: (body: PublicAccessUpdate) =>
      api.put<Project>(apiProjectPublicAccessPath(project.id), body),
    onSuccess: () => {
      invalidateEntities(queryClient, Entity.project, Entity.role);
    },
    onError: (error: Error) => pushToast(error.message),
  });
  const isPublic = Boolean(project.public);
  const contributions = Boolean(project.contributions);
  const disabled = !canManage || save.isPending;
  return (
    <section className="rounded-lg border border-subtle bg-surface p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-heading">
        <Globe size={15} aria-hidden className="text-fg-muted" />
        Public access
      </h2>
      <p className="mt-1 text-xs text-fg-secondary">
        A public project's <strong>public</strong> issues, their public comments and attachments are
        readable by anyone on the web without signing in. Internal and restricted issues stay hidden
        from the world whatever is switched on here.
      </p>
      <div className="mt-3 flex flex-col gap-2">
        <label className="flex items-center gap-2 text-sm text-fg">
          <input
            type="checkbox"
            checked={isPublic}
            disabled={disabled}
            onChange={(event) =>
              save.mutate({
                public: event.target.checked,
                contributions: event.target.checked ? contributions : false,
              })
            }
            className="size-4 accent-accent disabled:opacity-50"
          />
          Public project
          <span className="text-xs text-fg-muted">— grants the Public role to Anyone</span>
        </label>
        <label className="flex items-center gap-2 text-sm text-fg">
          <input
            type="checkbox"
            checked={contributions}
            disabled={disabled || !isPublic}
            onChange={(event) => save.mutate({ public: true, contributions: event.target.checked })}
            className="size-4 accent-accent disabled:opacity-50"
          />
          <UserRoundPlus size={14} aria-hidden className="text-fg-muted" />
          Anyone signed in may contribute
          <span className="text-xs text-fg-muted">
            — file issues, comment and attach (the Contributor role to Signed-in users)
          </span>
        </label>
      </div>
    </section>
  );
}
