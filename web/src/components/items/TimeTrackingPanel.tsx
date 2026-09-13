import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, Pencil, Plus, Trash2, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import {
  apiItemEstimatePath,
  apiItemWorklogsPath,
  apiWorklogPath,
} from "../../lib/constants";
import { useCurrentUser, usePermissions } from "../../lib/hooks";
import {
  itemTimelogQuery,
  queryKeys,
  workCategoriesQuery,
} from "../../lib/queries";
import {
  Permission,
  type EstimateSet,
  type ItemTimeSummary,
  type Project,
  type Worklog,
  type WorklogCreate,
  type WorklogUpdate,
} from "../../lib/types";
import { Button } from "../Button";
import { Select } from "../Select";
import { IconButton } from "../IconButton";
import { ErrorText } from "../ErrorText";
import { todayIso } from "../../lib/dates";

interface Props {
  project: Project;
  itemId: string;
  /** The collapsed face of the rail widget: totals + bar only — no estimate
   * editor, no log form, no per-entry list. Expanding the section flips this. */
  compact?: boolean;
}

/**
 * Issue-page time-tracking panel (spec 22). Rendered only when time logging is
 * enabled on the project. Shows the estimate/logged/remaining bar, a compact
 * log-work form, and the worklog entries (edit/delete own, or any as a manager).
 */
export function TimeTrackingPanel({ project, itemId, compact = false }: Props) {
  const perms = usePermissions();
  const summary = useQuery(itemTimelogQuery(itemId));
  const canWrite = perms.project(project, Permission.worklogWrite);
  const canEstimate = perms.project(project, Permission.itemUpdate);

  if (summary.isPending) return <p className="text-xs text-fg-faint">Loading time tracking…</p>;
  if (summary.isError)
    return <p className="text-xs text-red-400">Failed to load: {errorMessage(summary.error)}</p>;

  const data = summary.data;
  if (compact) {
    return (
      <div className="flex flex-col gap-1.5">
        <TimeBar summary={data} />
        <p className="text-[11px] text-fg-muted">
          {/* The bar above already says "No estimate" — only the ORIGINAL
              estimate (which the bar doesn't show) earns a mention here. */}
          {data.original_estimate ? `Estimate: ${data.original_estimate} · ` : ""}
          {data.entries.length} {data.entries.length === 1 ? "entry" : "entries"}
        </p>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <TimeBar summary={data} />
      <EstimateEditor itemId={itemId} summary={data} canEdit={canEstimate} />
      {canWrite && <LogWorkForm itemId={itemId} />}
      <WorklogList project={project} itemId={itemId} entries={data.entries} />
    </div>
  );
}

/** Logged-vs-estimate progress bar (green under, amber over). */
function TimeBar({ summary }: { summary: ItemTimeSummary }) {
  const est = summary.original_estimate_seconds;
  const logged = summary.logged_seconds;
  const over = est !== null && logged > est;
  const pct = est && est > 0 ? Math.min(100, (logged / est) * 100) : logged > 0 ? 100 : 0;
  return (
    <div>
      <div className="flex items-baseline justify-between text-[13px]">
        <span className="text-fg">
          <span className="font-medium text-heading">{summary.logged}</span> logged
        </span>
        {est !== null ? (
          <span className={over ? "text-amber-400" : "text-fg-muted"}>
            {summary.remaining_seconds !== null && summary.remaining_seconds < 0
              ? `${summary.remaining?.replace(/^-?/, "")} over`
              : `${summary.remaining} remaining`}
          </span>
        ) : (
          <span className="text-fg-faint">No estimate</span>
        )}
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-elevated">
        <div
          className={`h-full rounded-full ${over ? "bg-amber-500" : "bg-emerald-500"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function EstimateEditor({
  itemId,
  summary,
  canEdit,
}: {
  itemId: string;
  summary: ItemTimeSummary;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(summary.original_estimate ?? "");

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.itemTimelog(itemId) });
  const save = useMutation({
    mutationFn: (estimate: string) =>
      estimate.trim()
        ? api.put<ItemTimeSummary>(apiItemEstimatePath(itemId), {
            estimate: estimate.trim(),
          } satisfies EstimateSet)
        : api.delete<ItemTimeSummary>(apiItemEstimatePath(itemId)),
    onSuccess: () => {
      invalidate();
      setEditing(false);
    },
  });

  if (!canEdit) {
    return (
      <p className="text-xs text-fg-muted">
        Estimate: <span className="text-fg">{summary.original_estimate ?? "—"}</span>
      </p>
    );
  }

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => {
          setValue(summary.original_estimate ?? "");
          setEditing(true);
        }}
        className="flex w-fit items-center gap-1.5 text-xs text-fg-muted hover:text-fg cursor-pointer"
      >
        <Pencil size={11} aria-hidden />
        Estimate: <span className="text-fg">{summary.original_estimate ?? "set…"}</span>
      </button>
    );
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(value);
      }}
      className="flex items-center gap-2"
    >
      <label className="text-xs text-fg-muted">Estimate</label>
      <input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="e.g. 1d 4h"
        autoFocus
        className="w-28 rounded border border-strong bg-surface px-2 py-1 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
      />
      <Button type="submit" disabled={save.isPending}>
        {save.isPending ? "…" : "Save"}
      </Button>
      <button
        type="button"
        onClick={() => setEditing(false)}
        aria-label="Cancel"
        className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
      >
        <X size={13} />
      </button>
      {save.isError && <span className="text-xs text-red-400">{errorMessage(save.error)}</span>}
    </form>
  );
}

const DURATION_HINT = "2h 30m";

/** Compact form to log a new worklog entry. */
function LogWorkForm({ itemId }: { itemId: string }) {
  const queryClient = useQueryClient();
  const categories = useQuery(workCategoriesQuery());
  const [open, setOpen] = useState(false);
  const [timeSpent, setTimeSpent] = useState("");
  const [workedOn, setWorkedOn] = useState(() => todayIso());
  const [categoryId, setCategoryId] = useState("");
  const [note, setNote] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.post<Worklog>(apiItemWorklogsPath(itemId), {
        time_spent: timeSpent.trim(),
        worked_on: workedOn,
        category_id: categoryId || null,
        note: note.trim(),
      } satisfies WorklogCreate),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.itemTimelog(itemId) });
      void invalidateEntities(queryClient, Entity.worklog);
      setTimeSpent("");
      setNote("");
      setCategoryId("");
      setOpen(false);
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (timeSpent.trim()) create.mutate();
  };

  if (!open) {
    return (
      <Button variant="secondary" size="sm" className="w-fit" onClick={() => setOpen(true)}>
        <Plus size={12} aria-hidden />
        Log work
      </Button>
    );
  }

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-col gap-2 rounded-xl border border-subtle bg-elevated p-3"
    >
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-[11px] text-fg-muted">
          Time spent
          <input
            value={timeSpent}
            onChange={(event) => setTimeSpent(event.target.value)}
            placeholder={DURATION_HINT}
            autoFocus
            className="w-24 rounded border border-strong bg-surface px-2 py-1 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-fg-muted">
          Date
          <input
            type="date"
            value={workedOn}
            onChange={(event) => setWorkedOn(event.target.value)}
            className="rounded border border-strong bg-surface px-2 py-1 text-[13px] text-heading focus:outline-2 focus:outline-offset-1 focus:outline-focus"
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-fg-muted">
          Category
          <Select
            value={categoryId}
            onChange={setCategoryId}
            size="sm"
            options={[
              { value: "", label: "None" },
              ...(categories.data ?? []).map((category) => ({
                value: category.id,
                label: category.name,
              })),
            ]}
          />
        </label>
      </div>
      <input
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="Note (optional)"
        maxLength={2000}
        className="w-full rounded border border-strong bg-surface px-2 py-1 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
      />
      {create.isError && <ErrorText error={create.error} />}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
        <Button type="submit" disabled={create.isPending || !timeSpent.trim()}>
          {create.isPending ? "Logging…" : "Log work"}
        </Button>
      </div>
    </form>
  );
}

function WorklogList({
  project,
  itemId,
  entries,
}: {
  project: Project;
  itemId: string;
  entries: Worklog[];
}) {
  const me = useCurrentUser();
  const perms = usePermissions();
  const canManageAll = perms.project(project, Permission.projectManage);

  if (entries.length === 0) {
    return <p className="text-xs text-fg-faint">No work logged yet.</p>;
  }
  return (
    <ul className="flex flex-col gap-1.5">
      {entries.map((entry) => (
        <WorklogRow
          key={entry.id}
          itemId={itemId}
          entry={entry}
          canManage={canManageAll || me?.id === entry.author.id}
        />
      ))}
    </ul>
  );
}

function WorklogRow({
  itemId,
  entry,
  canManage,
}: {
  itemId: string;
  entry: Worklog;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [timeSpent, setTimeSpent] = useState(entry.time_spent);
  const [note, setNote] = useState(entry.note);
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.itemTimelog(itemId) });
    void invalidateEntities(queryClient, Entity.worklog);
  };

  const save = useMutation({
    mutationFn: () =>
      api.patch<Worklog>(apiWorklogPath(entry.id), {
        time_spent: timeSpent.trim(),
        note: note.trim(),
      } satisfies WorklogUpdate),
    onSuccess: () => {
      invalidate();
      setEditing(false);
    },
  });
  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiWorklogPath(entry.id)),
    onSuccess: invalidate,
  });

  if (editing) {
    return (
      <li className="flex items-center gap-2 rounded border border-subtle px-2 py-1.5">
        <input
          value={timeSpent}
          onChange={(event) => setTimeSpent(event.target.value)}
          className="w-20 rounded border border-strong bg-surface px-1.5 py-0.5 text-[13px] text-heading focus:outline-2 focus:outline-offset-1 focus:outline-focus"
        />
        <input
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Note"
          className="flex-1 rounded border border-strong bg-surface px-1.5 py-0.5 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
        />
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="rounded px-1.5 py-0.5 text-xs text-accent-text hover:bg-elevated cursor-pointer disabled:opacity-50"
        >
          Save
        </button>
        <button
          type="button"
          onClick={() => setEditing(false)}
          aria-label="Cancel"
          className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
        >
          <X size={13} />
        </button>
      </li>
    );
  }

  return (
    <li className="flex items-center gap-2 text-[13px]">
      <Clock size={12} className="shrink-0 text-fg-faint" aria-hidden />
      <span className="font-medium text-fg">{entry.time_spent}</span>
      <span className="text-fg-muted">{entry.author.name}</span>
      <span className="text-fg-faint">{entry.worked_on}</span>
      {entry.category && (
        <span className="rounded bg-elevated px-1.5 py-px text-[11px] text-fg">
          {entry.category.name}
        </span>
      )}
      {entry.note && <span className="truncate text-fg-muted">— {entry.note}</span>}
      {canManage && (
        <span className="ml-auto flex shrink-0 items-center gap-0.5">
          <IconButton
            onClick={() => {
              setTimeSpent(entry.time_spent);
              setNote(entry.note);
              setEditing(true);
            }}
            aria-label="Edit worklog"
          >
            <Pencil size={12} />
          </IconButton>
          <IconButton
            danger
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
            aria-label="Delete worklog"
          >
            <Trash2 size={12} />
          </IconButton>
        </span>
      )}
    </li>
  );
}
