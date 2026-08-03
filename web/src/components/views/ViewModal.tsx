import { useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SlotId, useDisabledMatches } from "@radd/plugin-sdk";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, RoutePath, apiViewPath, apiViewSharingPath, apiViewTransferPath } from "../../lib/constants";
import { SlqProbeStatus, usePermissions, useSlqValidation } from "../../lib/hooks";
import { capabilitiesQuery, fieldsQuery, queryKeys } from "../../lib/queries";
import { slqErrorOf } from "../../lib/slq";
import {
  Permission,
  ViewAxis,
  ViewType,
  type AxisToken,
  type Project,
  type QuickFilter,
  type ShareLevelValue,
  type View,
  type ViewCreate,
  type ViewSharingUpdate,
  type ViewTypeValue,
  type ViewUpdate,
} from "../../lib/types";
import { axisOptions } from "../../lib/view-utils";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { SelectField } from "../SelectField";
import { TextField } from "../TextField";
import { SlqCheatSheet } from "./SlqCheatSheet";
import { SlqEditor } from "./SlqEditor";
import { ViewSharingEditor, SERVER_PRIVATE, type LocalShare } from "./ViewSharingEditor";

interface ViewModalProps {
  /** View scope, fixed at open time: a project, or null = all-projects. */
  project: Project | null;
  /** When set, edit this view in place instead of creating one. */
  view?: View;
  onClose: () => void;
}

/** Sentinel for "no axis" in the pickers (never a valid axis token). */
const AXIS_NONE = "";

/**
 * New/Edit view dialog (spec 11): name, board/list/planning/queue/roadmap
 * type, shared toggle (unchanged gating), an SLQ query editor with debounced
 * live validation + match count and a collapsible syntax cheat sheet, and the
 * axis pickers — Columns (`group_by`) and Swimlanes (`swimlane_by`, boards
 * only, must differ) over the builtin axes + select-type registry fields
 * (`cf.<key>`). Planning, queue, and roadmap views ignore the axes (the
 * cycle-filter and WIP controls don't apply to roadmaps either).
 */
export function ViewModal({ project, view, onClose }: ViewModalProps) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const perms = usePermissions();

  // All-projects scope resolves "anywhere", not globally (RADD-788) — the
  // server's `_require_scope` makes the same call.
  const canShare = project
    ? perms.project(project, Permission.viewManage)
    : perms.anyProject(Permission.viewManage);

  const fields = useQuery(fieldsQuery());

  const [name, setName] = useState(view?.name ?? "");
  const [viewType, setViewType] = useState<string>(view?.view_type ?? ViewType.board);
  // Plugin-contributed view types (spec 94) join the Type dropdown; the plugin renders the surface.
  // A type whose `view.type` contribution has been turned off (per-user/instance-wide) drops out —
  // otherwise you could pick a type nothing can render.
  const { data: capsManifest } = useQuery(capabilitiesQuery);
  const disabledViewTypes = useDisabledMatches(SlotId.viewType);
  const pluginViewTypes = (capsManifest?.view_types ?? []).filter((t) => !disabledViewTypes.has(t.key));
  // Sharing (spec 57): the server-wide level + per-user/team grant rows; the
  // whole state saves atomically (inline on create, PUT /sharing on edit).
  // (`global_access` = the wire name for "everyone on this server".)
  const [serverAccess, setServerAccess] = useState<ShareLevelValue | typeof SERVER_PRIVATE>(
    view?.global_access ?? SERVER_PRIVATE,
  );
  const [shareRows, setShareRows] = useState<LocalShare[]>(
    (view?.shares ?? []).map((share) => ({
      kind: share.user ? "user" : "team",
      subjectId: (share.user ?? share.team)?.id ?? "",
      level: share.level,
    })),
  );
  // New views are always yours; existing ones only the owner (or, for legacy
  // owner-less views, a view-manage holder) may re-share.
  const canManageSharing = !view || view.can_manage;
  // Ownership transfer (spec 57): applied on save, after the sharing PUT.
  const [transferTo, setTransferTo] = useState("");
  const [query, setQuery] = useState(view?.query ?? "");
  const [groupBy, setGroupBy] = useState<string>(view?.group_by ?? AXIS_NONE);
  const [swimlaneBy, setSwimlaneBy] = useState<string>(view?.swimlane_by ?? AXIS_NONE);
  const [cycleFilter, setCycleFilter] = useState(view?.cycle_filter ?? "");
  const [quickFilters, setQuickFilters] = useState<QuickFilter[]>(view?.quick_filters ?? []);

  const probe = useSlqValidation(project?.id ?? null, query);

  const axes = axisOptions(fields.data ?? [], project?.id ?? null);
  // Planning views are always cycle-grouped, queues are always a flat triage
  // list (spec 64), and roadmaps are a timeline (spec 79) — the axis pickers
  // apply to none of them.
  const axesApply =
    viewType !== ViewType.planning &&
    viewType !== ViewType.queue &&
    viewType !== ViewType.roadmap;
  // Swimlanes: boards only, and never the same axis as the columns.
  const swimlanesApply = viewType === ViewType.board && groupBy !== AXIS_NONE;
  const laneAxes = axes.filter((axis) => axis.value !== groupBy);
  // The cycle-name filter only bites when a cycle axis is actually in play —
  // planning views are ALWAYS cycle-grouped, so they always get the field;
  // queues are never cycle-grouped (axes ignored, spec 64).
  const cycleAxisPicked =
    viewType === ViewType.planning ||
    (axesApply &&
      (groupBy === ViewAxis.cycle || (swimlanesApply && swimlaneBy === ViewAxis.cycle)));
  // Regex validity (spec 56) — checked live here, re-checked server-side (409).
  const cycleFilterError = useMemo(() => {
    if (!cycleAxisPicked || !cycleFilter.trim()) return null;
    try {
      new RegExp(cycleFilter.trim(), "i");
      return null;
    } catch (error) {
      return error instanceof Error ? error.message : "invalid pattern";
    }
  }, [cycleAxisPicked, cycleFilter]);

  const globalAccess = () => (serverAccess === SERVER_PRIVATE ? null : serverAccess);
  // Initial shares for CREATE (create_view still takes them → access grants).
  const shareEntries = () =>
    shareRows
      .filter((row) => row.subjectId !== "")
      .map((row) =>
        row.kind === "user"
          ? { user_id: row.subjectId, level: row.level }
          : { team_id: row.subjectId, level: row.level },
      );

  /** On EDIT, per-subject shares are access grants (spec 92): reconcile the local
   * rows against the view's current grants — add the new, delete the gone. */
  const reconcileShares = async () => {
    if (!view) return;
    const current = (view.shares ?? []).map((s) => ({
      id: s.id,
      key: s.user ? `user:${s.user.id}` : `team:${s.team!.id}`,
      level: s.level as string,
    }));
    const desired = shareRows
      .filter((r) => r.subjectId)
      .map((r) => ({ key: `${r.kind}:${r.subjectId}`, level: r.level as string }));
    const desiredKeys = new Set(desired.map((d) => `${d.key}@${d.level}`));
    const currentKeys = new Set(current.map((c) => `${c.key}@${c.level}`));
    for (const c of current) {
      if (!desiredKeys.has(`${c.key}@${c.level}`)) await api.delete(`${ApiPath.grants}/${c.id}`);
    }
    for (const d of desired) {
      if (currentKeys.has(`${d.key}@${d.level}`)) continue;
      const [kind, id] = d.key.split(":");
      await api.post(ApiPath.grants, {
        resource_type: "view",
        resource_id: view.id,
        subject_type: kind,
        subject_id: id,
        access: d.level,
        project_ids: [],
      });
    }
  };

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        name: name.trim(),
        view_type: viewType as ViewTypeValue,
        query,
        group_by: groupBy === AXIS_NONE ? null : (groupBy as AxisToken),
        swimlane_by:
          swimlanesApply && swimlaneBy !== AXIS_NONE && swimlaneBy !== groupBy
            ? (swimlaneBy as AxisToken)
            : null,
        cycle_filter: cycleAxisPicked ? cycleFilter.trim() || null : null,
        quick_filters: quickFilters
          .map((entry) => ({ name: entry.name.trim(), query: entry.query.trim() }))
          .filter((entry) => entry.name && entry.query),
      };
      if (view) {
        let saved = await api.patch<View>(apiViewPath(view.id), payload satisfies ViewUpdate);
        if (canManageSharing) {
          saved = await api.put<View>(apiViewSharingPath(view.id), {
            global_access: globalAccess(),
          } satisfies ViewSharingUpdate);
          await reconcileShares();
          // Transfer LAST — after it we may no longer hold manage rights.
          if (transferTo) {
            saved = await api.post<View>(apiViewTransferPath(view.id), { user_id: transferTo });
          }
        }
        return saved;
      }
      return api.post<View>(ApiPath.views, {
        ...payload,
        project_id: project?.id ?? null,
        global_access: globalAccess(),
        shares: shareEntries(),
      } satisfies ViewCreate);
    },
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.views });
      onClose();
      if (!view) {
        // Jump straight into the freshly created view.
        if (project) {
          void navigate({
            to: RoutePath.projectView,
            params: { projectKey: project.key, viewId: saved.id },
          });
        } else {
          void navigate({ to: RoutePath.allProjectsView, params: { viewId: saved.id } });
        }
      }
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim() && probe.status !== SlqProbeStatus.invalid && !cycleFilterError) {
      save.mutate();
    }
  };

  // The server re-parses on save — a 422 here means the draft outran the probe.
  const saveSlqError = save.isError ? slqErrorOf(save.error) : null;

  return (
    <Modal title={view ? "Edit view" : "New view"} onClose={onClose} wide>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="FX urgent"
            maxLength={100}
            required
          />
          <SelectField
            label="Type"
            value={viewType}
            onChange={(event) => setViewType(event.target.value)}
          >
            <option value={ViewType.board}>Board</option>
            <option value={ViewType.list}>List</option>
            <option value={ViewType.planning}>Planning (backlog & cycles)</option>
            <option value={ViewType.queue}>Queue (triage list)</option>
            <option value={ViewType.roadmap}>Roadmap (timeline)</option>
            {pluginViewTypes.map((t) => (
              <option key={t.key} value={t.key}>
                {t.label}
              </option>
            ))}
          </SelectField>
        </div>

        <SlqEditor
          label={`Query${project ? ` (scope: ${project.key})` : " (all projects)"}`}
          value={query}
          onChange={setQuery}
          probe={probe}
          suggestScope={project ? { project_id: project.id } : {}}
        />
        <SlqCheatSheet fields={fields.data ?? []} projectId={project?.id ?? null} />

        {axesApply && (
        <div className="grid grid-cols-2 items-end gap-3">
          <SelectField
            label="Columns"
            value={groupBy}
            onChange={(event) => {
              setGroupBy(event.target.value);
              if (event.target.value === swimlaneBy) setSwimlaneBy(AXIS_NONE);
            }}
            hint={viewType === ViewType.board ? "Boards without columns fall back to state" : "Optional list sections"}
          >
            <option value={AXIS_NONE}>None</option>
            {axes.map((axis) => (
              <option key={axis.value} value={axis.value}>
                {axis.label}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Swimlanes"
            value={swimlanesApply ? swimlaneBy : AXIS_NONE}
            onChange={(event) => setSwimlaneBy(event.target.value)}
            disabled={!swimlanesApply}
            hint={
              viewType !== ViewType.board
                ? "Boards only"
                : groupBy === AXIS_NONE
                  ? "Pick columns first"
                  : "Rows across the columns — must differ"
            }
          >
            <option value={AXIS_NONE}>None</option>
            {laneAxes.map((axis) => (
              <option key={axis.value} value={axis.value}>
                {axis.label}
              </option>
            ))}
          </SelectField>
        </div>
        )}

        {cycleAxisPicked && (
          <div className="flex flex-col gap-1">
            <TextField
              label="Cycle filter (regex)"
              value={cycleFilter}
              onChange={(event) => setCycleFilter(event.target.value)}
              placeholder="e.g. PIPE  ·  ^TS - [0-9]+$  ·  PIPE|TS  (blank = all cycles)"
              maxLength={200}
              hint="Case-insensitive regex deciding which cycle headers show. Backlog always shows."
            />
            {cycleFilterError && (
              <p className="text-[11px] text-red-400" role="alert">
                Invalid regex: {cycleFilterError}
              </p>
            )}
          </div>
        )}

        <div className="flex flex-col gap-2">
          <span className="text-xs font-medium text-fg-secondary">
            Quick filters
            <span className="ml-1.5 font-normal text-fg-faint">
              — clickable chips that AND their condition into the view (no ORDER BY)
            </span>
          </span>
          {quickFilters.map((filter, index) => (
            <QuickFilterRow
              key={index}
              filter={filter}
              projectId={project?.id ?? null}
              onChange={(next) =>
                setQuickFilters((current) =>
                  current.map((entry, i) => (i === index ? next : entry)),
                )
              }
              onRemove={() =>
                setQuickFilters((current) => current.filter((_, i) => i !== index))
              }
            />
          ))}
          {quickFilters.length < 10 && (
            <button
              type="button"
              onClick={() =>
                setQuickFilters((current) => [...current, { name: "", query: "" }])
              }
              className="w-fit text-xs text-fg-muted hover:text-fg cursor-pointer"
            >
              + Add quick filter
            </button>
          )}
        </div>

        {canManageSharing && (
          <ViewSharingEditor
            serverAccess={serverAccess}
            onServerAccess={setServerAccess}
            shares={shareRows}
            onShares={setShareRows}
            canBroadcast={canShare}
            transferTo={view ? transferTo : undefined}
            onTransferTo={view ? setTransferTo : undefined}
          />
        )}

        {save.isError && !saveSlqError && (
          <p className="text-xs text-red-400">{errorMessage(save.error)}</p>
        )}
        {saveSlqError && (
          <p className="text-xs text-red-400">Query rejected on save: {saveSlqError.message}</p>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={
              !name.trim() ||
              probe.status === SlqProbeStatus.invalid ||
              Boolean(cycleFilterError) ||
              save.isPending
            }
          >
            {save.isPending ? "Saving…" : view ? "Save view" : "Create view"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/** One quick-filter row: label + a COMPACT SlqEditor, so chip conditions get the
 * same autocomplete + live validation as the main query (each row owns its probe). */
function QuickFilterRow({
  filter,
  projectId,
  onChange,
  onRemove,
}: {
  filter: QuickFilter;
  projectId: string | null;
  onChange: (next: QuickFilter) => void;
  onRemove: () => void;
}) {
  const probe = useSlqValidation(projectId, filter.query);
  return (
    <div className="flex items-start gap-2">
      <input
        value={filter.name}
        onChange={(event) => onChange({ ...filter, name: event.target.value })}
        placeholder="Label"
        maxLength={60}
        className="h-8 w-36 shrink-0 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading"
      />
      <div className="min-w-0 flex-1">
        <SlqEditor
          compact
          value={filter.query}
          onChange={(value) => onChange({ ...filter, query: value })}
          probe={probe}
          suggestScope={projectId ? { project_id: projectId } : {}}
          placeholder="SLQ condition, e.g. assignee = me"
        />
      </div>
      <button
        type="button"
        aria-label="Remove quick filter"
        onClick={onRemove}
        className="mt-1.5 rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer"
      >
        ×
      </button>
    </div>
  );
}
