import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Plus, Workflow, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, apiStatePath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { CATEGORY_META, CATEGORY_ORDER } from "../../lib/meta";
import { projectsQuery, queryKeys, statesQuery } from "../../lib/queries";
import {
  Permission,
  StateCategory,
  type State,
  type StateCategoryValue,
  type StateCreate,
  type StateUpdate,
} from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { SelectField } from "../../components/SelectField";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { TransitionsSection } from "../../components/settings/TransitionsSection";
import { QueryError } from "../../components/QueryError";

/**
 * Per-project workflow states (spec 50). The project comes from the URL context
 * (`projectId` prop) rather than an in-page picker; gating is on THAT project.
 */
export function StatesSettingsPage({ projectId }: { projectId?: string }) {
  const perms = usePermissions();
  const projects = useQuery(projectsQuery());
  const project = (projects.data ?? []).find((entry) => entry.id === projectId);
  // States are per-project: gate on THAT project's manage permission.
  const canManage = perms.project(project, Permission.stateManage);
  const states = useQuery({ ...statesQuery(projectId ?? ""), enabled: Boolean(projectId) });
  const sorted = useMemo(
    () => [...(states.data ?? [])].sort((a, b) => a.position - b.position),
    [states.data],
  );

  return (
    <SettingsPage
      title="Workflow states"
      description="States grouped into fixed categories. New projects start with the default set."
      info={
        <>
          States are the steps an item moves through (Backlog → In Progress → Done). Each maps to
          a fixed <em>category</em> that drives reporting and board columns; the name is yours.
          Reorder them to control how they list on boards.
        </>
      }
    >
      {projects.isPending || (projectId && states.isPending) ? (
        <TableSkeleton rows={5} />
      ) : !project ? (
        <EmptyState icon={Workflow} message="Project not found." />
      ) : states.isError ? (
        <QueryError label="states" error={states.error} />
      ) : (
        <>
          <ul className="rounded-lg border border-subtle">
            {sorted.map((state) => (
              <StateRow key={state.id} state={state} projectId={project.id} canManage={canManage} />
            ))}
            {sorted.length === 0 && (
              <li className="px-4 py-6 text-center text-sm text-fg-muted">No states yet.</li>
            )}
          </ul>
          {canManage && <AddStateForm projectId={project.id} />}
          <TransitionsSection project={project} states={sorted} canManage={canManage} />
        </>
      )}
    </SettingsPage>
  );
}

/** One state row: category dot + name, inline rename (PATCH /states/{id}). */
function StateRow({
  state,
  projectId,
  canManage,
}: {
  state: State;
  projectId: string;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(state.name);
  const category = CATEGORY_META[state.category];

  const rename = useMutation({
    mutationFn: (body: StateUpdate) => api.patch<State>(apiStatePath(state.id), body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.states(projectId) });
      setEditing(false);
    },
  });

  const submitRename = (event: FormEvent) => {
    event.preventDefault();
    const name = draft.trim();
    if (!name || name === state.name) {
      setEditing(false);
      setDraft(state.name);
      return;
    }
    rename.mutate({ name });
  };

  return (
    <li className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5 last:border-b-0">
      <span className={`size-2 shrink-0 rounded-full ${category.dotClassName}`} aria-hidden />
      {editing ? (
        <form onSubmit={submitRename} className="flex flex-1 items-center gap-2">
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            maxLength={100}
            autoFocus
            aria-label={`Rename ${state.name}`}
            className="h-7 flex-1 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading focus:outline-2 focus:outline-offset-1 focus:outline-focus"
          />
          <button
            type="submit"
            disabled={rename.isPending}
            aria-label="Save name"
            className="rounded p-1 text-emerald-400 hover:bg-elevated cursor-pointer disabled:opacity-50"
          >
            <Check size={14} />
          </button>
          <button
            type="button"
            aria-label="Cancel rename"
            onClick={() => {
              setEditing(false);
              setDraft(state.name);
            }}
            className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
          >
            <X size={14} />
          </button>
          {rename.isError && (
            <span className="text-xs text-red-400">{errorMessage(rename.error)}</span>
          )}
        </form>
      ) : (
        <>
          <span className="flex-1 text-[13px] text-heading">
            {state.name}
            {state.is_default && (
              <span className="ml-2 rounded border border-strong px-1 py-px text-[10px] uppercase tracking-wide text-fg-muted">
                Default
              </span>
            )}
          </span>
          <span className="text-xs text-fg-muted">{category.label}</span>
          <span className="w-8 text-right font-mono text-[11px] text-fg-faint">
            {state.position}
          </span>
          {canManage && (
            <button
              type="button"
              onClick={() => setEditing(true)}
              aria-label={`Rename ${state.name}`}
              className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer"
            >
              <Pencil size={13} />
            </button>
          )}
        </>
      )}
    </li>
  );
}

/** Add a state to the selected project (POST /states). */
function AddStateForm({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [category, setCategory] = useState<StateCategoryValue>(StateCategory.todo);

  const createState = useMutation({
    mutationFn: (body: StateCreate) => api.post<State>(ApiPath.states, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.states(projectId) });
      setName("");
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    createState.mutate({ project_id: projectId, name: name.trim(), category });
  };

  return (
    <form onSubmit={onSubmit} className="mt-4 flex items-end gap-3">
      <div className="flex-1">
        <TextField
          label="New state"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="In Review"
          maxLength={100}
        />
      </div>
      <SelectField
        label="Category"
        value={category}
        onChange={(event) => setCategory(event.target.value as StateCategoryValue)}
      >
        {CATEGORY_ORDER.map((value) => (
          <option key={value} value={value}>
            {CATEGORY_META[value].label}
          </option>
        ))}
      </SelectField>
      <Button type="submit" disabled={createState.isPending || !name.trim()}>
        <Plus size={14} aria-hidden />
        {createState.isPending ? "Adding…" : "Add state"}
      </Button>
      {createState.isError && (
        <span className="pb-2 text-xs text-red-400">{errorMessage(createState.error)}</span>
      )}
    </form>
  );
}
