import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { Trash2, TriangleAlert } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { RoutePath, apiProjectPath } from "../../lib/constants";
import { projectContentQuery } from "../../lib/queries";
import { pushToast, ToastKind } from "../../lib/toast";
import type { Project, ProjectContentSummary } from "../../lib/types";
import { Button, ButtonVariant } from "../Button";
import { Callout, CalloutKind } from "../Callout";
import { ErrorText } from "../ErrorText";
import { Modal } from "../Modal";
import { Spinner } from "../Spinner";
import { TextField } from "../TextField";

/** The counts the dialog knows how to name, in reading order. Anything else
 * the server reports (a plugin's noun) is ignored rather than mis-labelled. */
const DESTROYED: [string, string][] = [
  ["items", "issues"],
  ["comments", "comments"],
  ["attachments", "attachments"],
  ["releases", "releases"],
  ["views", "saved views"],
  ["forms", "intake forms"],
  ["fields", "custom fields scoped only to this project"],
  ["link_types", "link types scoped only to this project"],
];

function hours(seconds: number): string {
  return `${Math.round((seconds / 3600) * 10) / 10}h`;
}

/**
 * The Danger zone on Settings → Project → General (RADD-1174). Rendered only
 * for holders of the GLOBAL `project.delete` atom — a delegated project admin
 * never sees it, which is the permission model made visible.
 */
export function DeleteProjectCard({ project }: { project: Project }) {
  const [open, setOpen] = useState(false);
  return (
    <section data-project-danger className="rounded-lg border border-callout-danger-border/60 bg-surface p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-heading">
        <TriangleAlert size={15} aria-hidden className="text-callout-danger-ink" />
        Danger zone
      </h2>
      <p className="mt-1 text-xs text-fg-secondary">
        Deleting <span className="font-mono text-fg">{project.key}</span> removes every issue, comment,
        attachment, worklog, release, view and form in it. The audit log keeps a record of the
        deletion; nothing else survives, and there is no undo.
      </p>
      <div className="mt-3">
        <Button variant={ButtonVariant.dangerGhost} onClick={() => setOpen(true)}>
          <Trash2 size={14} aria-hidden />
          Delete project…
        </Button>
      </div>
      {open && <DeleteProjectDialog project={project} onClose={() => setOpen(false)} />}
    </section>
  );
}

/**
 * The confirmation: what goes (from the server's inspection, never guessed),
 * what blocks (with a way to the fix), and the KEY typed back before the button
 * enables — a project is not a row you should be able to lose to a mis-click.
 */
function DeleteProjectDialog({ project, onClose }: { project: Project; onClose: () => void }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [typed, setTyped] = useState("");
  const content = useQuery(projectContentQuery(project.id));

  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiProjectPath(project.id)),
    onSuccess: async () => {
      pushToast(`Project ${project.key} deleted`, ToastKind.success);
      onClose();
      await navigate({ to: RoutePath.projects });
      await invalidateEntities(queryClient, Entity.project, Entity.role);
    },
    onError: (error) => pushToast(errorMessage(error), ToastKind.error),
  });

  const summary: ProjectContentSummary | undefined = content.data;
  const destroyed = summary ? DESTROYED.filter(([key]) => (summary.counts[key] ?? 0) > 0) : [];
  const worklogs = summary?.counts.worklogs ?? 0;
  const blocked = (summary?.blockers.length ?? 0) > 0;
  const confirmed = typed.trim().toUpperCase() === project.key;

  return (
    <Modal title={`Delete ${project.key} — ${project.name}?`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <p className="text-xs text-fg-secondary">
          The project and everything in it will be permanently removed. This cannot be undone.
        </p>

        {content.isPending ? (
          <Spinner label="Checking what it holds…" />
        ) : content.isError ? (
          <ErrorText error={content.error} />
        ) : (
          <>
            {blocked && (
              <Callout kind={CalloutKind.warning}>
                <p className="font-medium">Something still routes mail into this project.</p>
                <ul className="mt-1 flex flex-col gap-0.5">
                  {summary?.blockers.map((blocker) => (
                    <li key={`${blocker.kind}-${blocker.id}`}>
                      {blocker.label}
                      {blocker.hint ? (
                        <>
                          {" — "}
                          <Link to={RoutePath.settingsEmail} className="underline">
                            {blocker.hint}
                          </Link>
                        </>
                      ) : null}
                    </li>
                  ))}
                </ul>
                <p className="mt-1">Repoint or remove it first; the deletion is refused until then.</p>
              </Callout>
            )}
            {destroyed.length === 0 && worklogs === 0 ? (
              <p className="text-xs text-fg-muted">It holds no issues, comments, attachments or worklogs.</p>
            ) : (
              <div className="rounded-md border border-subtle p-2.5">
                <p className="mb-1 text-[11px] uppercase tracking-wide text-fg-faint">Destroyed with it</p>
                <ul className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-fg">
                  {destroyed.map(([key, label]) => (
                    <li key={key}>
                      <span className="text-heading">{summary?.counts[key]}</span> {label}
                    </li>
                  ))}
                  {worklogs > 0 && (
                    <li>
                      <span className="text-heading">{worklogs}</span> time entries (
                      {hours(summary?.counts.worklog_seconds ?? 0)})
                    </li>
                  )}
                </ul>
              </div>
            )}
          </>
        )}

        <TextField
          label={`Type ${project.key} to confirm`}
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          disabled={blocked || remove.isPending}
        />

        <div className="flex justify-end gap-2">
          <Button variant={ButtonVariant.ghost} onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={ButtonVariant.danger}
            onClick={() => remove.mutate()}
            disabled={remove.isPending || content.isPending || content.isError || blocked || !confirmed}
          >
            <Trash2 size={14} aria-hidden />
            {remove.isPending ? "Deleting…" : "Delete permanently"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
