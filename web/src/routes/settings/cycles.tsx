import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  CalendarRange,
  ChevronDown,
  ChevronRight,
  Pencil,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, RoutePath, apiCyclePath, apiCycleSeriesPath } from "../../lib/constants";
import { WEEKDAY_LABELS, parseCycleName } from "../../lib/cycle-series";
import { formatDate } from "../../lib/dates";
import { usePermissions } from "../../lib/hooks";
import { CYCLE_STATUS_META } from "../../lib/meta";
import { cycleSeriesQuery, cyclesQuery, teamsQuery } from "../../lib/queries";
import {
  CycleStatus,
  Permission,
  type Cycle,
  type CycleCreate,
  type CycleSeries,
  type CycleSeriesUpdate,
  type CycleUpdate,
} from "../../lib/types";
import { CompleteCycleModal } from "../../components/cycles/CompleteCycleModal";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Modal } from "../../components/Modal";
import { Select } from "../../components/Select";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { TokenMultiSelect } from "../../components/TokenMultiSelect";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { QueryError } from "../../components/QueryError";

/** Date range, or "Not scheduled" for a draft (dateless) staging cycle. */
function dateRange(cycle: Cycle): string {
  if (!cycle.start_date || !cycle.end_date) return "Not scheduled";
  return `${formatDate(cycle.start_date)} – ${formatDate(cycle.end_date)}`;
}

export function CyclesSettingsPage() {
  const perms = usePermissions();
  const canManage = perms.global(Permission.cycleUpdate);
  const cycles = useQuery(cyclesQuery());
  const [modal, setModal] = useState<{ cycle: Cycle | null } | null>(null);
  const [completing, setCompleting] = useState<Cycle | null>(null);
  // This page is the ONLY place completed cycles are visible, so the list only
  // grows — a name filter is what makes it usable at 90+ cycles.
  const [filter, setFilter] = useState("");
  // Completed cycles are the bulk of the list and the least often wanted, so
  // they get their own folded section rather than burying the live ones.
  const [completedOpen, setCompletedOpen] = useState(false);
  const all = cycles.data ?? [];
  const needle = filter.trim().toLowerCase();
  const list = needle
    ? all.filter((cycle) => cycle.name.toLowerCase().includes(needle))
    : all;
  const live = list.filter((cycle) => cycle.status !== CycleStatus.completed);
  const completed = list.filter((cycle) => cycle.status === CycleStatus.completed);
  // While filtering, the fold opens itself: searching for a cycle that turns
  // out to be completed should FIND it, not hide it behind another click.
  const showCompleted = completedOpen || needle.length > 0;

  return (
    <SettingsPage
      title="Cycles"
      description="Global cycles, spanning every project. Status (draft / upcoming / active / completed) is derived from the dates — a cycle with no dates is a draft (staging) area to plan work into. Recurring labels auto-provision future drafts."
      actions={
        canManage && (
          <Button onClick={() => setModal({ cycle: null })}>
            <Plus size={14} aria-hidden />
            New cycle
          </Button>
        )
      }
    >
      {cycles.isPending ? (
        <TableSkeleton rows={4} />
      ) : cycles.isError ? (
        <QueryError label="cycles" error={cycles.error} />
      ) : all.length === 0 ? (
        <EmptyState
          icon={CalendarRange}
          message={canManage ? "No cycles yet — create one to start planning." : "No cycles yet."}
        />
      ) : (
        <>
          <div className="mb-3 flex items-center gap-2">
            <div className="relative min-w-0 flex-1">
              <Search
                size={14}
                aria-hidden
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-faint"
              />
              <input
                type="search"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Filter cycles by name…"
                aria-label="Filter cycles by name"
                className="h-8 w-full rounded-md border border-subtle bg-surface pl-8 pr-2.5 text-[13px] text-heading placeholder:text-fg-faint focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
              />
            </div>
            <span className="shrink-0 text-xs tabular-nums text-fg-muted">
              {needle ? `${list.length} of ${all.length}` : `${all.length} cycles`}
            </span>
          </div>
          {list.length === 0 ? (
            <EmptyState icon={CalendarRange} message={`No cycles match “${filter.trim()}”.`} />
          ) : (
            <>
              {live.length > 0 && (
                <ul className="rounded-lg border border-subtle">
                  {live.map((cycle) => (
                    <CycleRow
                      key={cycle.id}
                      cycle={cycle}
                      canManage={canManage}
                      onEdit={() => setModal({ cycle })}
                      onComplete={() => setCompleting(cycle)}
                    />
                  ))}
                </ul>
              )}

              {completed.length > 0 && (
                <section className={live.length > 0 ? "mt-4" : undefined}>
                  <button
                    type="button"
                    onClick={() => setCompletedOpen((open) => !open)}
                    aria-expanded={showCompleted}
                    className="flex w-full cursor-pointer items-center gap-2 rounded-md px-1 py-1.5 text-left hover:bg-elevated/60 focus-visible:outline-2 focus-visible:outline-focus"
                  >
                    {showCompleted ? (
                      <ChevronDown size={14} className="shrink-0 text-fg-muted" aria-hidden />
                    ) : (
                      <ChevronRight size={14} className="shrink-0 text-fg-muted" aria-hidden />
                    )}
                    <span className="text-xs font-semibold uppercase tracking-wide text-fg-secondary">
                      Completed
                    </span>
                    <span className="text-xs tabular-nums text-fg-faint">{completed.length}</span>
                    {needle && (
                      <span className="text-[11px] text-fg-faint">· matching “{filter.trim()}”</span>
                    )}
                  </button>
                  {showCompleted && (
                    <ul className="mt-1 rounded-lg border border-subtle">
                      {completed.map((cycle) => (
                        <CycleRow
                          key={cycle.id}
                          cycle={cycle}
                          canManage={canManage}
                          onEdit={() => setModal({ cycle })}
                          onComplete={() => setCompleting(cycle)}
                        />
                      ))}
                    </ul>
                  )}
                </section>
              )}
            </>
          )}
        </>
      )}

      <SeriesSection canManage={canManage} />

      {modal && (
        <CycleModal cycle={modal.cycle} onClose={() => setModal(null)} />
      )}
      {completing && (
        <CompleteCycleModal
          cycle={completing}
          cycles={list}
          onClose={() => setCompleting(null)}
        />
      )}
    </SettingsPage>
  );
}

/** Recurring series: per-label auto-provisioning config (created via the New-cycle
 * modal's Recurring checkbox; look-ahead + next number editable here). */
function SeriesSection({ canManage }: { canManage: boolean }) {
  const series = useQuery(cycleSeriesQuery());
  if (!series.data?.length) return null;
  return (
    <section className="mt-6">
      <h2 className="mb-1 text-sm font-semibold text-fg">Recurring series</h2>
      <p className="mb-2 text-xs text-fg-muted">
        Each label keeps its configured number of future cycles ready — drafts are created
        automatically when a cycle of the label is created or completed.
      </p>
      <ul className="rounded-lg border border-subtle">
        {series.data.map((row) => (
          <SeriesRow key={row.id} series={row} canManage={canManage} />
        ))}
      </ul>
    </section>
  );
}

function SeriesRow({ series, canManage }: { series: CycleSeries; canManage: boolean }) {
  const queryClient = useQueryClient();
  const [draftsAhead, setDraftsAhead] = useState(String(series.drafts_ahead));
  const [nextNumber, setNextNumber] = useState(String(series.next_number));
  const [weekday, setWeekday] = useState(
    series.start_weekday === null ? "" : String(series.start_weekday),
  );
  const [duration, setDuration] = useState(String(series.duration_days ?? 14));
  const dirty =
    Number(draftsAhead) !== series.drafts_ahead ||
    Number(nextNumber) !== series.next_number ||
    (weekday === "" ? null : Number(weekday)) !== series.start_weekday ||
    (weekday === "" ? null : Number(duration)) !== series.duration_days;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["cycle-series"] });
    void queryClient.invalidateQueries({ queryKey: ["cycles"] });
  };
  const save = useMutation({
    mutationFn: () =>
      api.patch<CycleSeries>(apiCycleSeriesPath(series.id), {
        drafts_ahead: Number(draftsAhead),
        next_number: Number(nextNumber),
        // "" = clear the cadence (explicit nulls) → back to dateless drafts
        start_weekday: weekday === "" ? null : Number(weekday),
        duration_days: weekday === "" ? null : Number(duration),
      } satisfies CycleSeriesUpdate),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiCycleSeriesPath(series.id)),
    onSuccess: invalidate,
  });

  return (
    <li className="flex flex-wrap items-center gap-3 border-b border-subtle/60 px-4 py-2.5 last:border-b-0">
      <span className="text-[13px] font-medium text-heading">{series.label}</span>
      <label className="ml-auto flex items-center gap-1.5 text-xs text-fg-secondary">
        Starts
        <Select
          value={weekday}
          onChange={setWeekday}
          disabled={!canManage}
          size="sm"
          aria-label="Starts"
          options={[
            { value: "", label: "Unscheduled" },
            ...WEEKDAY_LABELS.map((label, index) => ({
              value: String(index),
              label: `${label}s`,
            })),
          ]}
        />
      </label>
      <label className="flex items-center gap-1.5 text-xs text-fg-secondary">
        Days
        <input
          type="number"
          min={1}
          max={90}
          value={duration}
          disabled={!canManage || weekday === ""}
          onChange={(event) => setDuration(event.target.value)}
          className="h-7 w-14 rounded-md border border-strong bg-surface px-1.5 text-xs text-heading disabled:opacity-60"
        />
      </label>
      <label className="flex items-center gap-1.5 text-xs text-fg-secondary">
        Drafts ahead
        <input
          type="number"
          min={0}
          max={20}
          value={draftsAhead}
          onChange={(event) => setDraftsAhead(event.target.value)}
          disabled={!canManage}
          className="h-7 w-16 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading disabled:opacity-60"
        />
      </label>
      <label className="flex items-center gap-1.5 text-xs text-fg-secondary">
        Next number
        <input
          type="number"
          min={1}
          value={nextNumber}
          onChange={(event) => setNextNumber(event.target.value)}
          disabled={!canManage}
          className="h-7 w-20 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading disabled:opacity-60"
        />
      </label>
      {canManage && (
        <>
          <button
            type="button"
            onClick={() => save.mutate()}
            disabled={!dirty || save.isPending}
            className="rounded border border-strong px-2 py-0.5 text-xs text-fg hover:border-emphasis hover:text-heading cursor-pointer disabled:opacity-40"
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            onClick={() => remove.mutate()}
            title="Stop recurring (existing cycles are kept)"
            className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer"
          >
            <Trash2 size={13} />
          </button>
        </>
      )}
      {(save.isError || remove.isError) && (
        <span className="w-full text-xs text-red-400">
          {errorMessage(save.error ?? remove.error)}
        </span>
      )}
    </li>
  );
}

function CycleRow({
  cycle,
  canManage,
  onEdit,
  onComplete,
}: {
  cycle: Cycle;
  canManage: boolean;
  onEdit: () => void;
  onComplete: () => void;
}) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const status = CYCLE_STATUS_META[cycle.status];

  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiCyclePath(cycle.id)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cycles"] }),
  });

  return (
    <li className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5 last:border-b-0">
      <span className={`size-2 shrink-0 rounded-full ${status.dotClassName}`} aria-hidden />
      <Link
        to={RoutePath.cycle}
        params={{ cycleId: cycle.id }}
        className="text-[13px] font-medium text-heading hover:underline"
      >
        {cycle.name}
      </Link>
      <span className="rounded border border-strong px-1.5 py-px text-[10px] uppercase tracking-wide text-fg-secondary">
        {status.label}
      </span>
      {cycle.team_ids.length > 0 && (
        <span
          title="Team-restricted — only the associated teams (and admins) see this cycle"
          className="rounded border border-amber-400/40 bg-amber-500/10 px-1.5 py-px text-[10px] uppercase tracking-wide text-amber-300"
        >
          Restricted
        </span>
      )}
      {cycle.goal && (
        <span className="hidden truncate text-xs text-fg-muted md:inline">{cycle.goal}</span>
      )}
      <span className="ml-auto shrink-0 text-xs text-fg-muted">{dateRange(cycle)}</span>
      {canManage && cycle.status === CycleStatus.active && (
        <button
          type="button"
          onClick={onComplete}
          className="shrink-0 rounded border border-strong px-2 py-0.5 text-xs text-fg hover:border-emphasis hover:text-heading cursor-pointer"
        >
          Complete…
        </button>
      )}
      {canManage &&
        (confirming ? (
          <span className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => remove.mutate()}
              disabled={remove.isPending}
              className="rounded px-1.5 py-0.5 text-xs text-red-400 hover:bg-elevated cursor-pointer disabled:opacity-50"
            >
              {remove.isPending ? "Deleting…" : "Delete"}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              aria-label="Cancel delete"
              className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
            >
              <X size={13} />
            </button>
          </span>
        ) : (
          <>
            <button
              type="button"
              onClick={onEdit}
              aria-label={`Edit ${cycle.name}`}
              className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer"
            >
              <Pencil size={13} />
            </button>
            <button
              type="button"
              onClick={() => setConfirming(true)}
              aria-label={`Delete ${cycle.name}`}
              className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer"
            >
              <Trash2 size={13} />
            </button>
          </>
        ))}
      {remove.isError && <span className="text-xs text-red-400">{errorMessage(remove.error)}</span>}
    </li>
  );
}

function CycleModal({ cycle, onClose }: { cycle: Cycle | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const editing = Boolean(cycle);
  const [name, setName] = useState(cycle?.name ?? "");
  const [startDate, setStartDate] = useState(cycle?.start_date ?? "");
  const [endDate, setEndDate] = useState(cycle?.end_date ?? "");
  const [goal, setGoal] = useState(cycle?.goal ?? "");
  // Spec 60 visibility: none checked = public, else only those teams (+ admins).
  const teams = useQuery(teamsQuery());
  const [teamIds, setTeamIds] = useState<string[]>(cycle?.team_ids ?? []);
  // Recurring series (create only): "PIPE - 120" seeds label PIPE at 120; a bare
  // "PIPE" starts at the chosen number (import continuity).
  const [recurring, setRecurring] = useState(false);
  const [draftsAhead, setDraftsAhead] = useState(2);
  const [nextNumber, setNextNumber] = useState("");
  // Cadence: "" = no schedule (dateless drafts); else weekday index (0=Monday).
  const [startWeekday, setStartWeekday] = useState("");
  const [durationDays, setDurationDays] = useState(14);
  const nameHasNumber = parseCycleName(name.trim()) !== null;

  // Both-or-neither: a lone date is ambiguous. Blank both = a draft cycle;
  // explicit null clears dates on the backend (scheduled -> draft).
  const oneDateOnly = Boolean(startDate) !== Boolean(endDate);

  const save = useMutation({
    mutationFn: () =>
      editing
        ? api.patch<Cycle>(apiCyclePath(cycle!.id), {
            name: name.trim(),
            start_date: startDate || null,
            end_date: endDate || null,
            goal,
            team_ids: teamIds,
          } satisfies CycleUpdate)
        : api.post<Cycle>(ApiPath.cycles, {
            name: name.trim(),
            start_date: startDate || null,
            end_date: endDate || null,
            goal,
            recurring,
            drafts_ahead: draftsAhead,
            next_number: !nameHasNumber && nextNumber ? Number(nextNumber) : null,
            start_weekday: recurring && startWeekday !== "" ? Number(startWeekday) : null,
            duration_days: recurring && startWeekday !== "" ? durationDays : null,
            team_ids: teamIds,
          } satisfies CycleCreate),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["cycles"] });
      if (editing) await queryClient.invalidateQueries({ queryKey: ["cycle", { cycleId: cycle!.id }] });
      onClose();
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || oneDateOnly) return;
    save.mutate();
  };

  return (
    <Modal title={editing ? `Edit ${cycle!.name}` : "New cycle"} onClose={onClose}>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <TextField
          label="Name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="PIPE - 115"
          maxLength={200}
          required
        />
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="cycle-start" className="text-xs font-medium text-fg-secondary">
              Start date
            </label>
            <input
              id="cycle-start"
              type="date"
              value={startDate}
              onChange={(event) => setStartDate(event.target.value)}
              className="h-8 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading focus:outline-2 focus:outline-offset-1 focus:outline-focus [color-scheme:dark]"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="cycle-end" className="text-xs font-medium text-fg-secondary">
              End date
            </label>
            <input
              id="cycle-end"
              type="date"
              value={endDate}
              onChange={(event) => setEndDate(event.target.value)}
              className="h-8 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading focus:outline-2 focus:outline-offset-1 focus:outline-focus [color-scheme:dark]"
            />
          </div>
        </div>
        <p className={`text-xs ${oneDateOnly ? "text-red-400" : "text-fg-muted"}`}>
          {oneDateOnly
            ? "Set both dates, or leave both blank."
            : "Leave both blank for a draft (staging) cycle you can schedule later."}
        </p>
        <TextField
          label="Goal (optional)"
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          placeholder="What this cycle aims to ship"
        />
        {(teams.data ?? []).length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-fg-secondary">Visible to</span>
            <TokenMultiSelect
              value={teamIds}
              onChange={setTeamIds}
              options={(teams.data ?? []).map((team) => ({
                value: team.id,
                label: team.name,
              }))}
              placeholder="Everyone — or pick teams…"
              ariaLabel="Teams this cycle is visible to"
            />
            <p className="text-[11px] text-fg-faint">
              {teamIds.length === 0
                ? "Public — everyone sees this cycle."
                : "Only members of the selected teams (and admins) see this cycle."}
            </p>
          </div>
        )}
        {!editing && (
          <div className="flex flex-col gap-3 rounded-md border border-subtle bg-surface/40 p-3">
            <label className="flex items-center gap-2 text-[13px] text-fg">
              <input
                type="checkbox"
                checked={recurring}
                onChange={(event) => setRecurring(event.target.checked)}
                className="size-3.5 accent-accent"
              />
              Recurring cycle
              <span className="text-[11px] text-fg-muted">
                — future drafts of this label are created automatically
              </span>
            </label>
            {recurring && (
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="cycle-weekday" className="text-xs font-medium text-fg-secondary">
                    Starts on
                  </label>
                  <Select
                    id="cycle-weekday"
                    value={startWeekday}
                    onChange={setStartWeekday}
                    options={[
                      { value: "", label: "No schedule (dateless drafts)" },
                      ...WEEKDAY_LABELS.map((label, index) => ({
                        value: String(index),
                        label: `${label}s`,
                      })),
                    ]}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="cycle-duration" className="text-xs font-medium text-fg-secondary">
                    Duration (days)
                  </label>
                  <input
                    id="cycle-duration"
                    type="number"
                    min={1}
                    max={90}
                    value={durationDays}
                    disabled={startWeekday === ""}
                    onChange={(event) => setDurationDays(Number(event.target.value))}
                    title="14 = a two-week cycle; future cycles chain back-to-back"
                    className="h-8 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading disabled:opacity-60"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="cycle-ahead" className="text-xs font-medium text-fg-secondary">
                    Future drafts to keep
                  </label>
                  <input
                    id="cycle-ahead"
                    type="number"
                    min={0}
                    max={20}
                    value={draftsAhead}
                    onChange={(event) => setDraftsAhead(Number(event.target.value))}
                    className="h-8 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="cycle-next" className="text-xs font-medium text-fg-secondary">
                    Starting number
                  </label>
                  <input
                    id="cycle-next"
                    type="number"
                    min={1}
                    value={nameHasNumber ? String(parseCycleName(name.trim())?.number ?? "") : nextNumber}
                    disabled={nameHasNumber}
                    placeholder="1"
                    onChange={(event) => setNextNumber(event.target.value)}
                    title={
                      nameHasNumber
                        ? "Taken from the name's trailing number"
                        : "Where numbering begins (e.g. 120 to continue after a Jira import)"
                    }
                    className="h-8 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading disabled:opacity-60"
                  />
                </div>
              </div>
            )}
          </div>
        )}
        {save.isError && <p className="text-xs text-red-400">{errorMessage(save.error)}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending || !name.trim() || oneDateOnly}>
            {save.isPending ? "Saving…" : editing ? "Save changes" : "Create cycle"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
