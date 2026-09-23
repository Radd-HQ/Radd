import { useMemo, useState, type FormEvent } from "react";
import { Link } from "@tanstack/react-router";
import { RoutePath } from "../../lib/constants";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Check, Pencil, Plus, Trash2, Workflow, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, apiStatePath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { CATEGORY_META, CATEGORY_ORDER } from "../../lib/meta";
import { projectByIdQuery, queryKeys, stateCategoriesQuery, statesQuery } from "../../lib/queries";
import {
  Permission,
  StateCategory,
  type State,
  type StateCategoryValue,
  type StateCategoryRow,
  type StateCreate,
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
import { ThreadResolutionSection } from "../../components/settings/ThreadResolutionSection";
import { QueryError } from "../../components/QueryError";
import { IconButton } from "../../components/IconButton";
import { ErrorText } from "../../components/ErrorText";

/**
 * Per-project workflow states (spec 50). The project comes from the URL context
 * (`projectId` prop) rather than an in-page picker; gating is on THAT project.
 */
export function StatesSettingsPage({ projectId }: { projectId?: string }) {
  const perms = usePermissions();
  const projectQuery = useQuery(projectByIdQuery(projectId ?? ""));
  const project = projectQuery.data;
  // States are per-project: gate on THAT project's manage permission.
  const canManage = perms.project(project, Permission.stateManage);
  const states = useQuery({ ...statesQuery(projectId ?? ""), enabled: Boolean(projectId) });
  const categories = useQuery(stateCategoriesQuery());
  const me = useCurrentUser();
  const isInstanceAdmin = me?.instance_role === InstanceRole.admin;
  const sorted = useMemo(
    () => [...(states.data ?? [])].sort((a, b) => a.position - b.position),
    [states.data],
  );

  return (
    <SettingsPage history={{ entities: ["state", "workflow_transition"], projectId }}
      title="Workflow states"
      description="The steps an issue moves through (Backlog → In Progress → Done). Each state belongs to a category, which drives boards and reports; the names are yours. Order the states to set how they list on boards."
    >
      {(projectId && projectQuery.isPending) || (projectId && states.isPending) ? (
        <TableSkeleton rows={5} />
      ) : projectQuery.isError ? (
        <QueryError label="project" error={projectQuery.error} />
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
                categories={categories.data ?? []}
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
          <StateCategoriesCard
            categories={categories.data ?? []}
            canManage={isInstanceAdmin}
          />
          <TransitionsSection project={project} states={sorted} canManage={canManage} />
          {canManage && <ThreadResolutionSection project={project} />}
          <DoneSideEffects projectKey={project.key} />
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
  categories,
  siblings,
  neighborUp,
  neighborDown,
}: {
  state: State;
  projectId: string;
  canManage: boolean;
  categories: StateCategoryRow[];
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
          {/* RADD-853/854: the category is editable in place from the
              VOCABULARY rows — the semantic behaviour derives from the row's
              behaves_as server-side. */}
          {canManage && categories.length > 0 ? (
            <Select
              value={state.category_key}
              onChange={(value) => rename.mutate({ category: value })}
              options={categories
                .slice()
                .sort((a, b) => a.position - b.position)
                .map((row) => ({ value: row.key, label: row.name }))}
            />
          ) : (
            <span className="text-xs text-fg-muted">
              {categories.find((row) => row.key === state.category_key)?.name ?? category.label}
            </span>
          )}
          {canManage && (
            <span className="flex items-center">
              <IconButton
                onClick={() => neighborUp && swap.mutate(neighborUp)}
                disabled={!neighborUp || swap.isPending}
                aria-label={`Move ${state.name} up`}
              >
                <ArrowUp size={13} />
              </IconButton>
              <IconButton
                onClick={() => neighborDown && swap.mutate(neighborDown)}
                disabled={!neighborDown || swap.isPending}
                aria-label={`Move ${state.name} down`}
              >
                <ArrowDown size={13} />
              </IconButton>
            </span>
          )}
          {canManage && (
            <IconButton
              onClick={() => setEditing(true)}
              aria-label={`Rename ${state.name}`}
            >
              <Pencil size={13} />
            </IconButton>
          )}
          {canManage && (
            <IconButton
              danger
              onClick={() => setDeleting(true)}
              disabled={state.is_default}
              title={
                state.is_default
                  ? "The project's default state — make another state default first"
                  : `Delete ${state.name}`
              }
              aria-label={`Delete ${state.name}`}
            >
              <Trash2 size={13} />
            </IconButton>
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


/** RADD-854: manage the category VOCABULARY — the one tier above states.
 * Name, colour and order are the operator's; `behaves_as` anchors each row to
 * one of the six fixed behaviours so every report/sweep/guard keeps working.
 * Builtins rename and recolour but keep their behaviour and cannot be
 * deleted; custom rows delete only when no state references them. */
function StateCategoriesCard({
  categories,
  canManage,
}: {
  categories: StateCategoryRow[];
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [behavesAs, setBehavesAs] = useState<StateCategoryValue>(StateCategory.in_progress);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.stateCategories });
  const add = useMutation({
    mutationFn: () =>
      api.post<StateCategoryRow>(Api.stateCategories, {
        name: name.trim(),
        behaves_as: behavesAs,
      }),
    onSuccess: () => {
      setName("");
      return invalidate();
    },
  });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<StateCategoryRow> }) =>
      api.patch<StateCategoryRow>(`${Api.stateCategories}/${id}`, body),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${Api.stateCategories}/${id}`),
    onSuccess: invalidate,
  });
  const swap = useMutation({
    mutationFn: async ({ a, b }: { a: StateCategoryRow; b: StateCategoryRow }) => {
      await api.patch<StateCategoryRow>(`${Api.stateCategories}/${a.id}`, { position: b.position });
      await api.patch<StateCategoryRow>(`${Api.stateCategories}/${b.id}`, { position: a.position });
    },
    onSuccess: invalidate,
  });
  const sorted = [...categories].sort((a, b) => a.position - b.position);

  return (
    <section className="mt-6" aria-label="State categories">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-medium text-heading">
        Categories
        <span className="rounded bg-elevated px-1.5 py-px text-[10px] font-medium text-fg-secondary">
          Shared by every project
        </span>
      </h2>
      <p className="mb-2 text-xs text-fg-muted">
        The groups boards and reports sort states into. They are the same for every project, so
        a change here changes all of them{canManage ? "" : " — only instance admins can edit them"}.
        Each category <em>behaves as</em> one of six fixed kinds (triage, backlog, to do,
        in&nbsp;progress, done, canceled), which keeps reports and guards correct whatever you
        name things.
      </p>
      <ul className="rounded-lg border border-subtle">
        {sorted.map((row, index) => (
          <li
            key={row.id}
            className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2 last:border-b-0"
          >
            <input
              type="color"
              value={row.color ?? "#8b93a7"}
              onChange={(event) => patch.mutate({ id: row.id, body: { color: event.target.value } })}
              disabled={!canManage}
              aria-label={`Colour for ${row.name}`}
              className="size-5 shrink-0 cursor-pointer rounded border border-strong bg-transparent disabled:cursor-default"
            />
            <span className="flex-1 text-[13px] text-heading">
              {row.name}
              {row.is_builtin && (
                <span className="ml-2 rounded border border-strong px-1 py-px text-[10px] uppercase tracking-wide text-fg-muted">
                  Builtin
                </span>
              )}
            </span>
            <span className="text-xs text-fg-faint">
              behaves as {CATEGORY_META[row.behaves_as].label}
            </span>
            {canManage && (
              <>
                <IconButton
                  onClick={() => index > 0 && swap.mutate({ a: row, b: sorted[index - 1] })}
                  disabled={index === 0 || swap.isPending}
                  aria-label={`Move ${row.name} up`}
                >
                  <ArrowUp size={13} />
                </IconButton>
                <IconButton
                  onClick={() => index < sorted.length - 1 && swap.mutate({ a: row, b: sorted[index + 1] })}
                  disabled={index === sorted.length - 1 || swap.isPending}
                  aria-label={`Move ${row.name} down`}
                >
                  <ArrowDown size={13} />
                </IconButton>
                <IconButton
                  danger
                  onClick={() => remove.mutate(row.id)}
                  disabled={row.is_builtin || remove.isPending}
                  title={row.is_builtin ? "Builtin categories cannot be deleted" : `Delete ${row.name}`}
                  aria-label={`Delete ${row.name}`}
                >
                  <X size={14} />
                </IconButton>
              </>
            )}
          </li>
        ))}
      </ul>
      {canManage && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) add.mutate();
          }}
          className="mt-2 flex items-end gap-2"
        >
          <TextField
            label=""
            aria-label="New category name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="New category name"
            maxLength={100}
          />
          <Select
            value={behavesAs}
            onChange={(value) => setBehavesAs(value as StateCategoryValue)}
            options={CATEGORY_ORDER.map((cat) => ({
              value: cat,
              label: `behaves as ${CATEGORY_META[cat].label}`,
            }))}
          />
          <Button type="submit" disabled={!name.trim() || add.isPending}>
            <Plus size={13} aria-hidden />
            Add category
          </Button>
        </form>
      )}
      {(add.isError || patch.isError || remove.isError || swap.isError) && (
        <ErrorText className="mt-1" error={add.error ?? patch.error ?? remove.error ?? swap.error} />
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
    queryFn: ({ signal }) =>
      api.get<{ total: number }>(Api.itemsCount, {
        signal,
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
            ? "Counting the issues in this state…"
            : n === 0
              ? "No issues are in this state."
              : `${n} issue${n === 1 ? "" : "s"} in this state will move to:`}
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
          The move is recorded in each issue&apos;s history. Transitions referencing this
          state are removed with it.
        </p>
        {remove.isError && <ErrorText error={remove.error} />}
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


/** RADD-1286: what else happens when work reaches a done state — configured on
 *  the project's General page, named here so the workflow page tells the whole story. */
function DoneSideEffects({ projectKey }: { projectKey: string }) {
  return (
    <section className="mt-8" aria-label="When work is done">
      <h3 className="text-sm font-medium text-heading">When work is done</h3>
      <p className="mt-1 text-xs text-fg-muted">
        Moving an issue into a done state can also email its requesters and send them a
        satisfaction survey. Both are set under{" "}
        <Link to={RoutePath.projectSettingsGeneral} params={{ projectKey }} className="text-accent-text hover:underline">
          General
        </Link>{" "}
        (Resolution emails, CSAT surveys).
      </p>
    </section>
  );
}
