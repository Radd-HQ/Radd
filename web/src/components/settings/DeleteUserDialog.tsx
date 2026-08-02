import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { TriangleAlert, Trash2 } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { apiUserPath } from "../../lib/constants";
import { queryKeys, userContentQuery } from "../../lib/queries";
import { pushToast, ToastKind } from "../../lib/toast";
import type { User, UserContentSummary } from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { SelectField } from "../SelectField";
import { PersonName } from "../PersonName";
import { Spinner } from "../Spinner";

/** The things that MOVE to the successor, in the order the dialog reads best. */
const MOVES: [keyof UserContentSummary, string][] = [
  ["reported_items", "issues reported"],
  ["assigned_items", "issues assigned"],
  ["comments", "comments"],
  ["documents", "pages pages"],
  ["views", "saved views"],
  ["dashboards", "dashboards"],
  ["owned_teams", "teams owned"],
  ["attachments", "attachments"],
  ["approvals", "approvals raised"],
];

function hours(seconds: number): string {
  return `${Math.round((seconds / 3600) * 10) / 10}h`;
}

/**
 * Hard-delete a user (spec 89) — the account row really goes, so the dialog's
 * job is to make the consequences legible BEFORE it happens: what moves, what is
 * destroyed, and who ends up owning it.
 */
export function DeleteUserDialog({
  user,
  candidates,
  onClose,
}: {
  user: User;
  candidates: User[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [successor, setSuccessor] = useState("");
  const content = useQuery(userContentQuery(user.id));

  const remove = useMutation({
    mutationFn: () =>
      api.delete<void>(
        successor ? `${apiUserPath(user.id)}?reassign_to=${successor}` : apiUserPath(user.id),
      ),
    onSuccess: async () => {
      pushToast(`${user.name} deleted`, ToastKind.success);
      await queryClient.invalidateQueries({ queryKey: queryKeys.users });
      await queryClient.invalidateQueries({ queryKey: ["usersAdmin"] });
      onClose();
    },
    onError: (error) => pushToast(errorMessage(error), ToastKind.error),
  });

  const summary = content.data;
  const moving = summary ? MOVES.filter(([key]) => Number(summary[key]) > 0) : [];
  const ownsSomething = moving.length > 0 || Number(summary?.worklogs ?? 0) > 0;
  // A successor is only required when something would otherwise be orphaned, so
  // clearing out placeholder accounts stays a single confirm.
  const needsSuccessor = ownsSomething;

  return (
    <Modal title={`Delete ${user.name}?`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <p className="text-xs text-fg-secondary">
          <span className="text-fg">{user.email}</span> will be permanently removed —
          this is not a deactivation and cannot be undone.
        </p>

        {content.isPending ? (
          <Spinner label="Checking what they own…" />
        ) : content.isError ? (
          <p className="text-xs text-red-400">{errorMessage(content.error)}</p>
        ) : !ownsSomething ? (
          <p className="text-xs text-fg-muted">
            They haven't created anything, so there is nothing to hand over.
          </p>
        ) : (
          <>
            {moving.length > 0 && (
              <div className="rounded-md border border-subtle p-2.5">
                <p className="mb-1 text-[11px] uppercase tracking-wide text-fg-faint">
                  Moves to the person you choose
                </p>
                <ul className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-fg">
                  {moving.map(([key, label]) => (
                    <li key={key}>
                      <span className="text-heading">{String(summary?.[key])}</span> {label}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {Number(summary?.worklogs ?? 0) > 0 && (
              <p className="flex items-start gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/5 p-2.5 text-xs text-amber-200">
                <TriangleAlert size={13} className="mt-0.5 shrink-0" aria-hidden />
                <span>
                  <strong className="font-medium">
                    {summary?.worklogs} time entries ({hours(Number(summary?.worklog_seconds ?? 0))})
                    will be deleted
                  </strong>{" "}
                  — not reassigned. Crediting someone else with hours they didn't work would
                  skew every timesheet and time report. Export them first if you need them.
                </span>
              </p>
            )}
          </>
        )}

        {needsSuccessor && (
          <SelectField
            label="Who inherits their work?"
            value={successor}
            onChange={(event) => setSuccessor(event.target.value)}
            hint="Required — everything above is reassigned to this person."
          >
            <option value="">Choose a user…</option>
            {candidates.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                <PersonName user={candidate} /> · {candidate.email}
              </option>
            ))}
          </SelectField>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            className="text-red-300"
            onClick={() => remove.mutate()}
            disabled={remove.isPending || content.isPending || (needsSuccessor && !successor)}
          >
            <Trash2 size={14} aria-hidden />
            {remove.isPending ? "Deleting…" : "Delete permanently"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
