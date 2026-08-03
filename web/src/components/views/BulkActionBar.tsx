import { useState } from "react";
import { PersonName } from "../PersonName";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArrowRightLeft, Flag, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { useCurrentUser, useItemWritability } from "../../lib/hooks";
import { PRIORITY_META, PRIORITY_ORDER } from "../../lib/meta";
import {
  cyclesQuery,
  issueTypesQuery,
  labelsQuery,
  projectsQuery,
  releasesQuery,
  statesQuery,
  teamsQuery,
  usersQuery,
} from "../../lib/queries";
import { pushToast, ToastKind } from "../../lib/toast";
import { Permission } from "../../lib/types";
import type {
  BulkMoveResult,
  BulkSkipReasonValue,
  BulkSkipped,
  BulkUpdateResult,
  ItemBulkPatch,
  PriorityValue,
  Project,
} from "../../lib/types";
import { BACKLOG_KEY, selectableCycles } from "../../lib/view-utils";
import { Button } from "../Button";
import { useCan } from "../../lib/can";
import { Modal } from "../Modal";
import { Select } from "../Select";

interface BulkActionBarProps {
  selectedIds: Set<string>;
  /** Set when the surface is project-scoped — enables State/Type/Release
   *  pickers (those are per-project values; bulk state by id can't span). */
  project: Project | null;
  /** "Select all N matching" (spec 68): the view's true match count + a
   *  handler that swaps the selection for the full id set. */
  matching?: { total: number; onSelectAll: () => void; pending: boolean };
  onClear: () => void;
}

const NONE = "__none__";

const REASON_LABELS: Record<BulkSkipReasonValue, string> = {
  not_found: "not found",
  forbidden: "no permission",
  invalid_target: "not applicable",
  transition_blocked: "blocked by transition rules",
  error: "failed",
};

function skippedSummary(skipped: BulkSkipped[]): string {
  const counts = new Map<string, number>();
  for (const entry of skipped) {
    const label = REASON_LABELS[entry.reason] ?? entry.reason;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  const parts = [...counts.entries()].map(([label, count]) => `${count} ${label}`);
  return `Skipped ${skipped.length} (${parts.join(", ")})`;
}

/**
 * Floating bulk-action bar (specs 24 + 68): apply one change to every selected
 * item through `POST /items/bulk-update` — per-item RBAC/guards apply server
 * side and failures are skipped and reported, never failing the batch. Also
 * hosts the cross-project move flow and the select-all-matching control.
 */
export function BulkActionBar({
  selectedIds,
  project,
  matching,
  onClear,
}: BulkActionBarProps) {
  const queryClient = useQueryClient();
  const currentUser = useCurrentUser();
  const [moving, setMoving] = useState(false);
  // On a single-project surface, disable field actions the user can't write (spec 92) — dimmed, with
  // a reason. Cross-project selections (project === null) can't be pre-resolved per item, so they
  // keep the server's per-item skip-and-report path.
  const writ = useItemWritability(project);
  // Already gated correctly by spec 96 — what was missing is the DECLARATION.
  // Without `data-needs` the restricted-access proof cannot tell a disabled
  // control from an absent one, so a correct gate and a missing gate looked
  // identical to it (RADD-778).
  const can = useCan();
  const editGate = can(Permission.itemUpdate, { project, verb: "edit these issues" });
  const locked = (field: string) => project != null && !writ.fieldWritable(field);

  // Option sources are fetched lazily — the bar only mounts with a selection.
  const cycles = useQuery(cyclesQuery());
  const labels = useQuery(labelsQuery());
  const teams = useQuery(teamsQuery());
  const users = useQuery(usersQuery);
  const projects = useQuery(projectsQuery());
  const states = useQuery({ ...statesQuery(project?.id ?? ""), enabled: Boolean(project) });
  const types = useQuery({ ...issueTypesQuery(project?.id ?? ""), enabled: Boolean(project) });
  const releases = useQuery({ ...releasesQuery(project?.id ?? ""), enabled: Boolean(project) });

  const bulkUpdate = useMutation({
    mutationFn: (patch: ItemBulkPatch) =>
      api.post<BulkUpdateResult>(ApiPath.itemsBulkUpdate, {
        item_ids: [...selectedIds],
        patch,
      }),
    onSuccess: (result) => {
      void invalidateEntities(queryClient, Entity.item);
      const summary = `Updated ${result.updated.length}`;
      if (result.skipped.length > 0) {
        pushToast(`${summary} · ${skippedSummary(result.skipped)}`);
      } else {
        pushToast(summary, ToastKind.success);
      }
    },
    onError: (error) => pushToast(`Bulk update failed: ${errorMessage(error)}`),
  });
  const apply = (patch: ItemBulkPatch) => bulkUpdate.mutate(patch);

  const bulkMove = useMutation({
    mutationFn: (targetProjectId: string) =>
      api.post<BulkMoveResult>(ApiPath.itemsBulkMove, {
        item_ids: [...selectedIds],
        target_project_id: targetProjectId,
      }),
    onSuccess: (result, targetProjectId) => {
      void invalidateEntities(queryClient, Entity.item);
      const target = (projects.data ?? []).find((entry) => entry.id === targetProjectId);
      const summary = `Moved ${result.moved.length} to ${target?.key ?? "project"} — keys changed, old links keep redirecting`;
      if (result.skipped.length > 0) {
        pushToast(`${summary} · ${skippedSummary(result.skipped)}`);
      } else {
        pushToast(summary, ToastKind.success);
      }
      setMoving(false);
      onClear();
    },
    onError: (error) => pushToast(`Move failed: ${errorMessage(error)}`),
  });

  // A value-select that fires once and snaps back to its placeholder. `field` names the writability
  // key: on a single-project surface the select disables (dimmed, with a reason) when it's locked.
  const actionSelect = (
    label: string,
    options: { value: string; label: React.ReactNode }[],
    onPick: (value: string) => void,
    field: string,
  ) => {
    const isLocked = locked(field);
    return (
      <Select
        aria-label={label}
        disabled={isLocked}
        title={isLocked ? writ.reasonFor(field) : undefined}
        size="sm"
        className="max-w-36"
        value=""
        onChange={(value) => {
          if (value) onPick(value);
        }}
        options={[{ value: "", label }, ...options]}
      />
    );
  };

  const clearable = (id: string) => (id === NONE ? null : id);
  const moveTargets = projects.data ?? [];

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-40 flex justify-center px-4">
      <div className="pointer-events-auto flex flex-wrap items-center gap-2 rounded-lg border border-strong bg-surface/95 px-3 py-2 shadow-2xl shadow-black/40 backdrop-blur">
        <span className="text-[13px] font-medium text-fg">
          {selectedIds.size} selected
        </span>
        {matching && matching.total > selectedIds.size && (
          <button
            type="button"
            onClick={matching.onSelectAll}
            disabled={matching.pending}
            className="text-xs text-accent-text hover:text-accent-text-strong cursor-pointer disabled:opacity-50"
          >
            {matching.pending ? "Selecting…" : `Select all ${matching.total} matching`}
          </button>
        )}
        <span className="h-5 w-px bg-strong" aria-hidden />

        {project &&
          actionSelect(
            "State…",
            (states.data ?? []).map((state) => ({ value: state.id, label: state.name })),
            (value) => apply({ state_id: value }),
            "state",
          )}
        {actionSelect(
          "Priority…",
          PRIORITY_ORDER.map((priority) => ({
            value: priority,
            label: PRIORITY_META[priority].label,
          })),
          (value) => apply({ priority: value as PriorityValue }),
          "priority",
        )}
        {actionSelect(
          "Assignee…",
          [
            ...(currentUser ? [{ value: currentUser.id, label: "Me" }] : []),
            { value: NONE, label: "Unassigned" },
            ...(users.data ?? [])
              .filter((user) => user.active && user.id !== currentUser?.id)
              .map((user) => ({ value: user.id, label: <PersonName user={user} /> })),
          ],
          (value) => apply({ assignee_id: clearable(value) }),
          "assignee",
        )}
        {actionSelect(
          "Team…",
          [
            { value: NONE, label: "No team" },
            ...(teams.data ?? []).map((team) => ({ value: team.id, label: team.name })),
          ],
          (value) => apply({ team_id: clearable(value) }),
          "team",
        )}
        {project &&
          (types.data ?? []).length > 0 &&
          actionSelect(
            "Type…",
            (types.data ?? []).map((type) => ({ value: type.id, label: type.name })),
            (value) => apply({ type_id: value }),
            "type",
          )}
        {actionSelect(
          "Cycle…",
          [
            { value: BACKLOG_KEY, label: "Backlog" },
            ...selectableCycles(cycles.data).map((cycle) => ({ value: cycle.id, label: cycle.name })),
          ],
          (value) => apply({ cycle_id: value === BACKLOG_KEY ? null : value }),
          "cycle",
        )}
        {project &&
          (releases.data ?? []).length > 0 &&
          actionSelect(
            "Release…",
            [
              { value: NONE, label: "No release" },
              ...(releases.data ?? []).map((release) => ({
                value: release.id,
                label: release.version,
              })),
            ],
            (value) => apply({ release_id: clearable(value) }),
            "release",
          )}
        {(labels.data ?? []).length > 0 &&
          actionSelect(
            "+ Label…",
            (labels.data ?? []).map((label) => ({ value: label.name, label: label.name })),
            (value) => apply({ add_labels: [value] }),
            "labels",
          )}
        {(labels.data ?? []).length > 0 &&
          actionSelect(
            "− Label…",
            (labels.data ?? []).map((label) => ({ value: label.name, label: label.name })),
            (value) => apply({ remove_labels: [value] }),
            "labels",
          )}

        <Button
          variant="ghost"
          disabled={locked("flagged")}
          title={locked("flagged") ? writ.reasonFor("flagged") : undefined}
          onClick={() => apply({ flagged: true })}
        >
          <Flag size={13} aria-hidden />
          Flag
        </Button>
        <Button
          variant="ghost"
          {...editGate.props}
          disabled={editGate.props.disabled || (project != null && !writ.canEdit)}
          title={project != null && !writ.canEdit ? writ.reasonFor("archived") : editGate.props.title}
          onClick={() => apply({ archived: true })}
        >
          <Archive size={13} aria-hidden />
          Archive
        </Button>
        {moveTargets.length > 1 && (
          <Button variant="ghost" onClick={() => setMoving(true)}>
            <ArrowRightLeft size={13} aria-hidden />
            Move…
          </Button>
        )}
        {bulkUpdate.isPending && (
          <span className="text-xs text-fg-muted">Applying…</span>
        )}

        <span className="h-5 w-px bg-strong" aria-hidden />
        <button
          type="button"
          onClick={onClear}
          aria-label="Clear selection"
          className="rounded p-1 text-fg-secondary hover:bg-elevated hover:text-heading cursor-pointer"
        >
          <X size={15} />
        </button>
      </div>

      {moving && (
        <div className="pointer-events-auto">
          <BulkMoveDialog
            count={selectedIds.size}
            projects={moveTargets}
            pending={bulkMove.isPending}
            onMove={(projectId) => bulkMove.mutate(projectId)}
            onClose={() => setMoving(false)}
          />
        </div>
      )}
    </div>
  );
}

function BulkMoveDialog({
  count,
  projects,
  pending,
  onMove,
  onClose,
}: {
  count: number;
  projects: Project[];
  pending: boolean;
  onMove: (projectId: string) => void;
  onClose: () => void;
}) {
  const [target, setTarget] = useState("");
  return (
    <Modal title={`Move ${count} item${count === 1 ? "" : "s"} to another project`} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-xs leading-relaxed text-fg-secondary">
          Items are re-keyed by the target project's counter (old keys keep
          redirecting). States and types map by name, releases are cleared, and
          custom fields the target doesn't define are dropped. Items keep their
          parent/child links — select sub-items too if they should move along.
        </p>
        <Select
          aria-label="Target project"
          className="w-full"
          value={target}
          onChange={setTarget}
          placeholder="Choose a project…"
          options={projects.map((entry) => ({
            value: entry.id,
            label: `${entry.key} — ${entry.name}`,
          }))}
        />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!target || pending} onClick={() => target && onMove(target)}>
            {pending ? "Moving…" : "Move items"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
