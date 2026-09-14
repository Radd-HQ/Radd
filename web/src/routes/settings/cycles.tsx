import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  CalendarRange,
  Pencil,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, RoutePath, apiCyclePath } from "../../lib/constants";
import { WEEKDAY_LABELS, parseCycleName } from "../../lib/cycle-series";
import { formatDate } from "../../lib/dates";
import { usePermissions } from "../../lib/hooks";
import { useCycleDirectory } from "../../lib/useCycleDirectory";
import { DirectoryPager } from "../../components/DirectoryPager";
import { CYCLE_STATUS_META } from "../../lib/meta";
import { cycleSummaryQuery } from "../../lib/queries";
import {
  CycleStatus,
  Permission,
  type Cycle,
  type CycleCreate,
  type CycleUpdate,
  type CycleStatusValue,
} from "../../lib/types";
import { SeriesSection } from "../../components/cycles/SeriesSection";
import { CompleteCycleModal } from "../../components/cycles/CompleteCycleModal";
import { Button } from "../../components/Button";
import { ListSearchInput } from "../../components/ListSearchInput";
import { EmptyState } from "../../components/EmptyState";
import { Modal } from "../../components/Modal";
import { Select } from "../../components/Select";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { TeamAudience } from "../../components/teams/TeamAudience";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { QueryError } from "../../components/QueryError";
import { IconButton } from "../../components/IconButton";
import { ErrorText } from "../../components/ErrorText";

/** Date range, or "Not scheduled" for a draft (dateless) staging cycle. */
function dateRange(cycle: Cycle): string {
  if (!cycle.start_date || !cycle.end_date) return "Not scheduled";
  return `${formatDate(cycle.start_date)} – ${formatDate(cycle.end_date)}`;
}

const CycleFilter = { live: "live", all: "all" } as const;
type CycleFilterValue = CycleStatusValue | typeof CycleFilter[keyof typeof CycleFilter];

export function CyclesSettingsPage() {
  const perms = usePermissions();
  const canManage = perms.global(Permission.cycleUpdate);
  const canDelete = perms.global(Permission.cycleDelete);
  const [status, setStatus] = useState<CycleFilterValue>(CycleFilter.live);
  const cycles = useCycleDirectory({
    status: status === CycleFilter.live || status === CycleFilter.all ? undefined : status,
    includeCompleted: status !== CycleFilter.live,
  });
  const counts = useQuery(cycleSummaryQuery(cycles.q));
  const total = Object.values(counts.data ?? {}).reduce((sum, count) => sum + count, 0);
  const [modal, setModal] = useState<{ cycle: Cycle | null } | null>(null);
  const [completing, setCompleting] = useState<Cycle | null>(null);

  return <SettingsPage history={{ entities: ["cycle", "cycle_series"] }} title="Cycles"
    description="Global cycles span projects. Dates determine draft, upcoming, active or completed status; recurring series keep future cycles ready."
    actions={perms.global(Permission.cycleCreate) && <Button onClick={() => setModal({ cycle: null })}><Plus size={14} aria-hidden />New cycle</Button>}>
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <ListSearchInput className="min-w-48 flex-1" value={cycles.filter} onChange={cycles.setFilter}
        placeholder="Filter cycles by name…" total={total} matched={cycles.total} noun="cycles" />
      <Select value={status} onChange={value => setStatus(value as CycleFilterValue)} aria-label="Cycle status"
        options={[
          { value: CycleFilter.live, label: "Active, upcoming and draft" },
          { value: CycleFilter.all, label: "All statuses" },
          ...Object.values(CycleStatus).map(value => ({ value, label: `${CYCLE_STATUS_META[value].label} (${counts.data?.[value] ?? 0})` })),
        ]} />
    </div>
    <div aria-busy={cycles.busy}>
      {cycles.isPending ? <TableSkeleton rows={4} />
        : cycles.isError ? <QueryError label="cycles" error={cycles.error} />
        : cycles.rows.length === 0 ? <EmptyState icon={CalendarRange}
          message={cycles.filter ? `No cycles match “${cycles.filter.trim()}” in this status.` : "No cycles in this status."} />
        : <ul className="rounded-lg border border-subtle">{cycles.rows.map(cycle =>
          <CycleRow key={cycle.id} cycle={cycle} canManage={canManage} canDelete={canDelete}
            onEdit={() => setModal({ cycle })} onComplete={() => setCompleting(cycle)} />
        )}</ul>}
      <DirectoryPager {...cycles} onPage={cycles.setPage} label="cycles" />
    </div>
    <SeriesSection canManage={canManage} canDelete={canDelete} />
    {modal && <CycleModal cycle={modal.cycle} onClose={() => setModal(null)} />}
    {completing && <CompleteCycleModal cycle={completing} onClose={() => setCompleting(null)} />}
  </SettingsPage>;
}


function CycleRow({
  cycle,
  canManage,
  canDelete,
  onEdit,
  onComplete,
}: {
  cycle: Cycle;
  canManage: boolean;
  canDelete: boolean;
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
    <li className="flex min-w-0 flex-wrap items-center gap-3 border-b border-subtle/60 px-4 py-2.5 last:border-b-0">
      <span className={`size-2 shrink-0 rounded-full ${status.dotClassName}`} aria-hidden />
      <Link
        to={RoutePath.cycle}
        params={{ cycleId: cycle.id }}
        className="min-w-0 break-words text-[13px] font-medium text-heading hover:underline"
      >
        {cycle.name}
      </Link>
      <span className="rounded border border-strong px-1.5 py-px text-[10px] uppercase tracking-wide text-fg-secondary">
        {status.label}
      </span>
      {cycle.team_ids.length > 0 && (
        <span
          title="Team-restricted — only the associated teams (and admins) see this cycle"
          className="rounded border border-status-warning/40 bg-status-warning/10 px-1.5 py-px text-[10px] uppercase tracking-wide text-status-warning-ink"
        >
          Restricted
        </span>
      )}
      {cycle.goal && (
        <span className="hidden truncate text-xs text-fg-muted md:inline">{cycle.goal}</span>
      )}
      <span className="ml-auto shrink-0 text-xs text-fg-muted">{dateRange(cycle)}</span>
      {canManage && cycle.status === CycleStatus.active && (
        <Button variant="secondary" size="sm" className="shrink-0" onClick={onComplete}>
          Complete…
        </Button>
      )}
      {canManage && <IconButton onClick={onEdit} aria-label={`Edit ${cycle.name}`}>
        <Pencil size={13} />
      </IconButton>}
      {canDelete && (confirming ? (
        <span className="flex items-center gap-1">
          <Button variant="danger-ghost" size="sm" onClick={() => remove.mutate()} disabled={remove.isPending}>
            {remove.isPending ? "Deleting…" : "Delete"}
          </Button>
          <IconButton onClick={() => setConfirming(false)} aria-label="Cancel delete"><X size={13} /></IconButton>
        </span>
      ) : <IconButton danger onClick={() => setConfirming(true)} aria-label={`Delete ${cycle.name}`}>
        <Trash2 size={13} />
      </IconButton>)}
      {remove.isError && <span className="text-xs text-status-danger-ink">{errorMessage(remove.error)}</span>}
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
  // Spec 60 visibility: none chosen = public, else only those teams (+ admins).
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
        <p className={`text-xs ${oneDateOnly ? "text-status-danger-ink" : "text-fg-muted"}`}>
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
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-secondary">Visible to</span>
          {/* The bounded team picker (RADD-1115): the draft holds every chosen
              id, one page of names mounts, and choices come from the searched
              directory rather than a full team list. */}
          <TeamAudience
            value={teamIds}
            onChange={setTeamIds}
            emptyText="Public — everyone sees this cycle."
            hint="Only members of the selected teams (and admins) see this cycle."
          />
        </div>
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
        {save.isError && <ErrorText error={save.error} />}
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
