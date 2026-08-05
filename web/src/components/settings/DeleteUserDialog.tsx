import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { apiUserPath } from "../../lib/constants";
import { queryKeys, successorCheckQuery, userContentQuery } from "../../lib/queries";
import { pushToast, ToastKind } from "../../lib/toast";
import type { User, UserContentSummary } from "../../lib/types";
import { Button } from "../Button";
import { Callout } from "../Callout";
import { Modal } from "../Modal";
import { SelectField } from "../SelectField";
import { PersonName } from "../PersonName";
import { Spinner } from "../Spinner";
import { ErrorText } from "../ErrorText";

/** The things that MOVE to the successor, in the order the dialog reads best.
 * Owned teams are NOT here (RADD-784): running a team is delegation, not
 * content — they go ownerless, called out separately below. */
const MOVES: [keyof UserContentSummary, string][] = [
  ["reported_items", "issues reported"],
  ["assigned_items", "issues assigned"],
  ["comments", "comments"],
  ["documents", "wiki pages"],
  ["views", "saved views"],
  ["dashboards", "dashboards"],
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
  // RADD-784: access never transfers, so the candidate must already hold at
  // least what this account holds — previewed here, enforced by the server.
  const check = useQuery({ ...successorCheckQuery(user.id, successor), enabled: !!successor });

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
  const notViable = !!successor && check.data ? !check.data.viable : false;
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
          <ErrorText error={content.error} />
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
              <Callout kind="warning">
                <strong className="font-medium">
                  {summary?.worklogs} time entries ({hours(Number(summary?.worklog_seconds ?? 0))})
                  will be deleted
                </strong>{" "}
                — not reassigned. Crediting someone else with hours they didn't work would
                skew every timesheet and time report. Export them first if you need them.
              </Callout>
            )}
          </>
        )}

        {Number(summary?.owned_teams ?? 0) > 0 && (
          <p className="text-xs text-fg-muted">
            The <span className="text-fg">{summary?.owned_teams}</span>{" "}
            {Number(summary?.owned_teams) === 1 ? "team they own goes" : "teams they own go"}{" "}
            ownerless — pick each team's new owner deliberately afterwards.
          </p>
        )}

        {needsSuccessor && (
          <SelectField
            label="Who inherits their work?"
            value={successor}
            onChange={(event) => setSuccessor(event.target.value)}
            hint="Required — the content above is reassigned to this person. Their access (projects, roles, teams) is NOT: it dies with the account."
          >
            <option value="">Choose a user…</option>
            {candidates.map((candidate) => (
              <option
                key={candidate.id}
                value={candidate.id}
                label={`${candidate.name} · ${candidate.email}`}
              >
                <PersonName user={candidate} /> · {candidate.email}
              </option>
            ))}
          </SelectField>
        )}

        {!!successor && check.isPending && <Spinner label="Checking their access…" />}
        {notViable && (
          <Callout kind="warning">
            <p className="font-medium">
              This person holds less access than {user.name}, so they can't inherit the work.
            </p>
            <p className="mt-1">Grant these first, or choose someone else:</p>
            <ul className="mt-1 flex flex-col gap-0.5">
              {check.data?.gaps.map((gap) => (
                <li key={`${gap.scope_type}-${gap.scope_id ?? gap.label}`}>
                  <span className="font-medium">{gap.label}</span>
                  {": "}
                  {gap.missing.slice(0, 8).join(", ")}
                  {gap.missing.length > 8 ? ` (+${gap.missing.length - 8} more)` : ""}
                </li>
              ))}
            </ul>
          </Callout>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            className="text-red-300"
            onClick={() => remove.mutate()}
            disabled={
              remove.isPending ||
              content.isPending ||
              (needsSuccessor && !successor) ||
              (!!successor && (check.isPending || notViable))
            }
          >
            <Trash2 size={14} aria-hidden />
            {remove.isPending ? "Deleting…" : "Delete permanently"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
