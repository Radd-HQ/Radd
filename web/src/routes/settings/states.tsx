import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Check, Pencil, Plus, Trash2, Workflow, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, apiStatePath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { CATEGORY_META, CATEGORY_ORDER } from "../../lib/meta";
import { projectsQuery, queryKeys, stateGroupsQuery, statesQuery } from "../../lib/queries";
import {
  Permission,
  StateCategory,
  type State,
  type StateCategoryValue,
  type StateCreate,
  type StateGroup,
  type StateUpdate,
} from "../../lib/types";
import { ApiPath as Api, apiStatePath as statePath } from "../../lib/constants";
import { Modal } from "../../components/Modal";
import { useCurrentUser } from "../../lib/hooks";
import { InstanceRole } from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Select } from "../../components/Select";
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
  const groups = useQuery(stateGroupsQuery());
  const me = useCurrentUser();
  const isInstanceAdmin = me?.instance_role === InstanceRole.admin;
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
            {sorted.map((state, index) => (
              <StateRow
                key={state.id}
                state={state}
                projectId={project.id}
                canManage={canManage}
                groups={groups.data ?? []}
                siblings={sorted}
                neighborUp={index > 0 ? sorted[index - 1] : null}
                neighborDown={index < sorted.length - 1 ? sorted[index + 1] : null}
              />
            ))}
            {sorted.length === 0 && (
              <li className="px-4 py-6 text-center text-sm text-fg-muted">No states yet.</li>
            )}
          </ul>
          {canManage && <AddStateForm projectId={project.id} />}
          <StateGroupsCard groups={groups.data ?? []} canManage={isInstanceAdmin} />
          <TransitionsSection project={project} states={sorted} canManage={canManage} />
        </>
      )}
    </SettingsPage>
  );
}

/** One state row: category dot + name, inline rename (PATCH /states/{id}),
 * and up/down reordering (RADD-850) — a move swaps `position` with the
 * neighbour, which is what boards, list sections and pickers all order by. */
function StateRow({
  state,
  projectId,
  canManage,
  groups,
  siblings,
  neighborUp,
  neighborDown,
}: {
  state: State;
  projectId: string;
  canManage: boolean;
  groups: StateGroup[];
  siblings: State[];
  neighborUp: State | null;
  neighborDown: State | null;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [draft, setDraft] = useState(state.name);
  const category = CATEGORY_META[state.category];

  const rename = useMutation({
    mutationFn: (body: StateUpdate) => api.patch<State>(apiStatePath(state.id), body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.states(projectId) });
      setEditing(false);
    },
  });
  const swap = useMutation({
    mutationFn: async (neighbor: State) => {
      await api.patch<State>(apiStatePath(state.id), { position: neighbor.position });
      await api.patch<State>(apiStatePath(neighbor.id), { position: state.position });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.states(projectId) }),
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
          {/* RADD-853: the category is editable in place — re-classifies the
              state's items for every category consumer from now on. */}
          {canManage ? (
            <Select
              value={state.category}
              onChange={(value) =>
                rename.mutate({ category: value as StateCategoryValue })
              }
              options={CATEGORY_ORDER.map((cat) => ({
                value: cat,
                label: CATEGORY_META[cat].label,
              }))}
            />
          ) : (
            <span className="text-xs text-fg-muted">{category.label}</span>
          )}
          {/* RADD-852: presentation-group membership — pure vocabulary, so the
              picker changes boards, never reports. */}
          {canManage && groups.length > 0 && (
            <Select
              value={state.group_id ?? ""}
              onChange={(value) => rename.mutate({ group_id: value === "" ? null : value })}
              options={[
                { value: "", label: "No group" },
                ...groups.map((group) => ({ value: group.id, label: group.name })),
              ]}
            />
          )}
          {!canManage && state.group_id && (
            <span className="text-xs text-fg-faint">
              {groups.find((g) => g.id === state.group_id)?.name}
            </span>
          )}
          {canManage && (
            <span className="flex items-center">
              <button
                type="button"
                onClick={() => neighborUp && swap.mutate(neighborUp)}
                disabled={!neighborUp || swap.isPending}
                aria-label={`Move ${state.name} up`}
                className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer disabled:cursor-default disabled:opacity-30"
              >
                <ArrowUp size={13} />
              </button>
              <button
                type="button"
                onClick={() => neighborDown && swap.mutate(neighborDown)}
                disabled={!neighborDown || swap.isPending}
                aria-label={`Move ${state.name} down`}
                className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer disabled:cursor-default disabled:opacity-30"
              >
                <ArrowDown size={13} />
              </button>
            </span>
          )}
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
          {canManage && (
            <button
              type="button"
              onClick={() => setDeleting(true)}
              disabled={state.is_default}
              title={
                state.is_default
                  ? "The project's default state — make another state default first"
                  : `Delete ${state.name}`
              }
              aria-label={`Delete ${state.name}`}
              className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer disabled:cursor-default disabled:opacity-30"
            >
              <Trash2 size={13} />
            </button>
          )}
          {deleting && (
            <DeleteStateDialog
              state={state}
              projectId={projectId}
              siblings={siblings}
              onClose={() => setDeleting(false)}
            />
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


/** RADD-852: manage the instance-wide presentation groups. Pure vocabulary —
 * a group changes how boards bucket, never what reports count — so the card
 * lives beside the states it groups. Writes are instance-admin. */
function StateGroupsCard({ groups, canManage }: { groups: StateGroup[]; canManage: boolean }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.stateGroups });
  const add = useMutation({
    mutationFn: () => api.post<StateGroup>(Api.stateGroups, { name: name.trim() }),
    onSuccess: () => {
      setName("");
      return invalidate();
    },
  });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<StateGroup> }) =>
      api.patch<StateGroup>(`${Api.stateGroups}/${id}`, body),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${Api.stateGroups}/${id}`),
    onSuccess: invalidate,
  });
  const swap = useMutation({
    mutationFn: async ({ a, b }: { a: StateGroup; b: StateGroup }) => {
      await api.patch<StateGroup>(`${Api.stateGroups}/${a.id}`, { position: b.position });
      await api.patch<StateGroup>(`${Api.stateGroups}/${b.id}`, { position: a.position });
    },
    onSuccess: invalidate,
  });
  const sorted = [...groups].sort((a, b) => a.position - b.position);

  return (
    <section className="mt-6" aria-label="State groups">
      <h2 className="mb-1 text-sm font-medium text-heading">State groups</h2>
      <p className="mb-2 text-xs text-fg-muted">
        Optional, instance-wide grouping for boards and swimlanes ("group by State group").
        Purely presentational: each state keeps its category, so reports and automations are
        untouched. Assign states to a group with the picker on each row above.
      </p>
      <ul className="rounded-lg border border-subtle">
        {sorted.map((group, index) => (
          <li
            key={group.id}
            className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2 last:border-b-0"
          >
            <input
              type="color"
              value={group.color ?? "#8b93a7"}
              onChange={(event) => patch.mutate({ id: group.id, body: { color: event.target.value } })}
              disabled={!canManage}
              aria-label={`Colour for ${group.name}`}
              className="size-5 shrink-0 cursor-pointer rounded border border-strong bg-transparent disabled:cursor-default"
            />
            <span className="flex-1 text-[13px] text-heading">{group.name}</span>
            {canManage && (
              <>
                <button
                  type="button"
                  onClick={() => index > 0 && swap.mutate({ a: group, b: sorted[index - 1] })}
                  disabled={index === 0 || swap.isPending}
                  aria-label={`Move ${group.name} up`}
                  className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer disabled:cursor-default disabled:opacity-30"
                >
                  <ArrowUp size={13} />
                </button>
                <button
                  type="button"
                  onClick={() => index < sorted.length - 1 && swap.mutate({ a: group, b: sorted[index + 1] })}
                  disabled={index === sorted.length - 1 || swap.isPending}
                  aria-label={`Move ${group.name} down`}
                  className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer disabled:cursor-default disabled:opacity-30"
                >
                  <ArrowDown size={13} />
                </button>
                <button
                  type="button"
                  onClick={() => remove.mutate(group.id)}
                  disabled={remove.isPending}
                  aria-label={`Delete ${group.name}`}
                  className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer"
                >
                  <X size={14} />
                </button>
              </>
            )}
          </li>
        ))}
        {sorted.length === 0 && (
          <li className="px-4 py-4 text-center text-xs text-fg-muted">
            No groups yet — states bucket by their own order until you add some.
          </li>
        )}
      </ul>
      {canManage && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) add.mutate();
          }}
          className="mt-2 flex items-center gap-2"
        >
          <TextField
            label=""
            aria-label="New group name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="New group name"
            maxLength={100}
          />
          <Button type="submit" disabled={!name.trim() || add.isPending}>
            <Plus size={13} aria-hidden />
            Add group
          </Button>
        </form>
      )}
      {(add.isError || patch.isError || remove.isError) && (
        <p className="mt-1 text-xs text-red-400">
          {errorMessage(add.error ?? patch.error ?? remove.error)}
        </p>
      )}
    </section>
  );
}


/** RADD-853: delete a state with a SUCCESSOR for its items — the spec-89
 * delete-with-a-successor precedent. The dialog names the item count and asks
 * where they go (defaulting to the project's default state); the move runs
 * server-side as an admin repair that records ordinary item history. */
function DeleteStateDialog({
  state,
  projectId,
  siblings,
  onClose,
}: {
  state: State;
  projectId: string;
  siblings: State[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const others = siblings.filter((s) => s.id !== state.id);
  const [successor, setSuccessor] = useState(
    others.find((s) => s.is_default)?.id ?? others[0]?.id ?? "",
  );
  const count = useQuery({
    queryKey: ["state-item-count", state.id] as const,
    queryFn: () =>
      api.get<{ total: number }>(Api.itemsCount, {
        query: { project_id: projectId, state_id: state.id },
      }),
  });
  const remove = useMutation({
    mutationFn: () =>
      api.delete(
        `${statePath(state.id)}?reassign_to=${encodeURIComponent(successor)}`,
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.states(projectId) });
      onClose();
    },
  });
  const n = count.data?.total;

  return (
    <Modal title={`Delete "${state.name}"`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <p className="text-[13px] text-fg-secondary">
          {n === undefined
            ? "Counting the items in this state…"
            : n === 0
              ? "No items are in this state."
              : `${n} item${n === 1 ? "" : "s"} in this state will move to:`}
        </p>
        {(n === undefined || n > 0) && (
          <Select
            value={successor}
            onChange={setSuccessor}
            options={others.map((s) => ({
              value: s.id,
              label: `${s.name}${s.is_default ? " (default)" : ""}`,
            }))}
          />
        )}
        <p className="text-xs text-fg-muted">
          The move is recorded in each item&apos;s history. Transitions referencing this
          state are removed with it.
        </p>
        {remove.isError && <p className="text-xs text-red-400">{errorMessage(remove.error)}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => remove.mutate()}
            disabled={remove.isPending || (others.length === 0 && (n ?? 1) > 0)}
            className="text-red-400"
          >
            {remove.isPending ? "Deleting…" : "Delete state"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
