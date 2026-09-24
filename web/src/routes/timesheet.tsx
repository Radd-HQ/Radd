import { Fragment, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, ChevronLeft, ChevronRight, Plus, Tag } from "lucide-react";
import { api } from "../lib/api";
import { ApiPath } from "../lib/constants";
import { TopBarQuery } from "../components/shell/TopBarSlot";
import { QueryBar } from "../components/views/QueryBar";
import { useSlqQueryState } from "../lib/slq-filter";
import { readUrlState, writeUrlState } from "../lib/url-state";
import {
  TimesheetGroupBy,
  TimesheetPeriod,
  type TimesheetGroupByValue,
  type TimesheetPeriodValue,
} from "../lib/constants";
import { formatDuration } from "../lib/duration";
import { useDurationConfig, usePeek, usePermissions } from "../lib/hooks";
import { useCan } from "../lib/can";
import {
  instanceConfigQuery,
  leaveCalendarQuery,
  projectsQuery,
  teamsQuery,
  timesheetQuery,
  usersQuery,
  workCategoriesQuery,
} from "../lib/queries";
import {
  Permission,
  type LeaveCalendarEntry,
  type Timesheet,
  type TimesheetEntry,
} from "../lib/types";
import { Avatar } from "../components/Avatar";
import { AwayChip } from "../components/PersonName";
import { PersonName } from "../components/PersonName";
import {
  categoryTotals,
  daysInRange,
  fromISODate,
  periodLabel,
  periodRange,
  pivotRows,
  shiftAnchor,
  toISODate,
  type TimesheetRow,
} from "../lib/timesheet";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { Modal } from "../components/Modal";
import { QueryError } from "../components/QueryError";
import { Select, type SelectOption } from "../components/Select";
import { SelectField } from "../components/SelectField";
import { Spinner } from "../components/Spinner";
import { Table, TBody, Td, THead, Th } from "../components/Table";
import { TextField } from "../components/TextField";
import { ErrorText } from "../components/ErrorText";
import { MirroredBadge } from "../components/items/MirroredBadge";
import { formatIso, todayIso } from "../lib/dates";

const PERIODS: { value: TimesheetPeriodValue; label: string }[] = [
  { value: TimesheetPeriod.day, label: "Day" },
  { value: TimesheetPeriod.week, label: "Week" },
  { value: TimesheetPeriod.month, label: "Month" },
];

/** Global timesheet (spec 22): day/week/month time reports, filterable by
 * team or person, drilling into a day / employee / issue. */
export function TimesheetPage() {
  const perms = usePermissions();
  const durationConfig = useDurationConfig();
  const canViewOthers = perms.global(Permission.timesheetView);

  // Everything that changes WHICH HOURS YOU SEE is URL state, so a refresh (or
  // a pasted link) lands on the same timesheet — same rule the view page
  // follows. `logging` and the log-work form below stay ephemeral: a half-typed
  // entry is not a screen anyone wants restored.
  const url = readUrlState();
  const [period, setPeriodState] = useState<TimesheetPeriodValue>(
    (url.p as TimesheetPeriodValue) ?? TimesheetPeriod.week,
  );
  const [anchor, setAnchorState] = useState(() => fromISODate(url.d ?? todayIso()));
  const [groupBy, setGroupByState] = useState<TimesheetGroupByValue>(
    (url.g as TimesheetGroupByValue) ?? TimesheetGroupBy.issue,
  );
  const [projectId, setProjectIdState] = useState(url.pr ?? "");
  const [teamId, setTeamIdState] = useState(url.tm ?? "");
  const [userId, setUserIdState] = useState(url.u ?? "");

  // Each setter mirrors into the URL. Defaults write null so a timesheet at its
  // defaults has a clean address rather than one restating them.
  const setPeriod = (value: TimesheetPeriodValue) => {
    setPeriodState(value);
    writeUrlState({ p: value === TimesheetPeriod.week ? null : value });
  };
  const setAnchor = (value: Date) => {
    setAnchorState(value);
    writeUrlState({ d: toISODate(value) });
  };
  const setGroupBy = (value: TimesheetGroupByValue) => {
    setGroupByState(value);
    writeUrlState({ g: value === TimesheetGroupBy.issue ? null : value });
  };
  const setProjectId = (value: string) => {
    setProjectIdState(value);
    writeUrlState({ pr: value || null });
  };
  const setTeamId = (value: string) => {
    setTeamIdState(value);
    writeUrlState({ tm: value || null });
  };
  const setUserId = (value: string) => {
    setUserIdState(value);
    writeUrlState({ u: value || null });
  };

  // Worklog SLQ (spec 98): the shared fetch-free query state — the commit is
  // a SERVER filter (the timesheet's rows come from one query, nothing to
  // intersect client-side).
  const slqFilter = useSlqQueryState(ApiPath.timesheet);

  const { start, end } = useMemo(() => periodRange(period, anchor), [period, anchor]);
  const days = useMemo(() => daysInRange(start, end), [start, end]);

  const projects = useQuery(projectsQuery());
  const teams = useQuery(teamsQuery());
  const users = useQuery({ ...usersQuery, enabled: canViewOthers });
  const timesheet = useQuery(
    timesheetQuery({
      start,
      end,
      projectId: projectId || undefined,
      q: slqFilter.committed || undefined,
      teamId: canViewOthers ? teamId || undefined : undefined,
      userId: canViewOthers ? userId || undefined : undefined,
    }),
  );

  const rows = useMemo(
    () => pivotRows(timesheet.data?.entries ?? [], groupBy),
    [timesheet.data, groupBy],
  );
  const byCategory = useMemo(
    () => categoryTotals(timesheet.data?.entries ?? []),
    [timesheet.data],
  );
  // Leave/holiday spans for the window, exploded to per-user day cells so the
  // grid renders (and outlier flags skip) exactly the occupied days.
  const leaveCal = useQuery(leaveCalendarQuery(start, end));
  const leaveByUserDay = useMemo(() => {
    const map = new Map<string, Map<string, LeaveCalendarEntry>>();
    for (const entry of leaveCal.data ?? []) {
      const from = entry.start_date > start ? entry.start_date : start;
      const to = entry.end_date < end ? entry.end_date : end;
      for (const day of daysInRange(from, to)) {
        let inner = map.get(entry.user_id);
        if (!inner) {
          inner = new Map();
          map.set(entry.user_id, inner);
        }
        inner.set(day, entry);
      }
    }
    return map;
  }, [leaveCal.data, start, end]);
  const [logging, setLogging] = useState(false);
  // General time needs worklog.write on SOME project (`can_log_general`), so
  // the question is cross-project. A read-only viewer reaches this page and
  // was offered a form whose save answered 403 (RADD-778).
  const logGate = useCan()(Permission.worklogWrite, { anyProject: true, verb: "log time" });

  return (
    <div className="flex h-full flex-col">
      {/* Worklog SLQ (spec 98) in the global top bar, same as views:
          `author = me AND issue.assignee != me`, `issue IS EMPTY AND
          category = "Code Review"`. `issue.` completes and compiles through
          the ITEM dialect, so every issue field works here. */}
      <TopBarQuery>
        <QueryBar
          filter={slqFilter}
          dialect={ApiPath.timesheet}
          nlDialect="worklog"
          placeholder={"Filter worklogs: author = me AND issue.assignee != me"}
        />
      </TopBarQuery>
      <header className="flex flex-wrap items-center gap-3 border-b border-subtle px-6 py-3.5">
        <h1 className="flex items-center gap-2 text-sm font-semibold text-heading">
          <CalendarClock size={16} aria-hidden />
          Timesheet
        </h1>
        <div className="flex overflow-hidden rounded-md border border-strong">
          {PERIODS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setPeriod(option.value)}
              className={`px-2.5 py-1 text-xs cursor-pointer ${
                period === option.value
                  ? "bg-strong text-heading"
                  : "text-fg-secondary hover:bg-elevated"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setAnchor(shiftAnchor(period, anchor, -1))}
            aria-label="Previous period"
            className="rounded p-1 text-fg-secondary hover:bg-elevated hover:text-heading cursor-pointer"
          >
            <ChevronLeft size={16} />
          </button>
          <Button variant="secondary" size="sm" onClick={() => setAnchor(fromISODate(todayIso()))}>
            Today
          </Button>
          <button
            type="button"
            onClick={() => setAnchor(shiftAnchor(period, anchor, 1))}
            aria-label="Next period"
            className="rounded p-1 text-fg-secondary hover:bg-elevated hover:text-heading cursor-pointer"
          >
            <ChevronRight size={16} />
          </button>
          <span className="ml-1 text-[13px] text-fg">{periodLabel(period, start, end)}</span>
        </div>
        <span className="ml-auto text-[13px] text-fg-secondary">
          Total:{" "}
          <span className="font-semibold text-heading">
            {formatDuration(timesheet.data?.total_seconds ?? 0, durationConfig)}
          </span>
        </span>
        <Button onClick={() => setLogging(true)} {...logGate.props}>
          <Plus size={14} aria-hidden />
          Log time
        </Button>
      </header>

      <div className="flex flex-wrap items-center gap-2 border-b border-subtle px-6 py-2 text-xs">
        <FilterSelect
          label="Group by"
          value={groupBy}
          onChange={(v) => setGroupBy(v as TimesheetGroupByValue)}
          options={[
            { value: TimesheetGroupBy.issue, label: "By issue" },
            { value: TimesheetGroupBy.epic, label: "By epic" },
            { value: TimesheetGroupBy.person, label: "By person" },
            { value: TimesheetGroupBy.category, label: "By category" },
          ]}
        />
        <FilterSelect
          label="Project"
          value={projectId}
          onChange={setProjectId}
          options={[
            { value: "", label: "All projects" },
            ...(projects.data ?? []).map((project) => ({
              value: project.id,
              label: project.key,
            })),
          ]}
        />
        {canViewOthers ? (
          <>
            <FilterSelect
              label="Team"
              value={teamId}
              onChange={setTeamId}
              options={[
                { value: "", label: "All teams" },
                ...(teams.data ?? []).map((team) => ({ value: team.id, label: team.name })),
              ]}
            />
            <FilterSelect
              label="Person"
              value={userId}
              onChange={setUserId}
              options={[
                { value: "", label: "Everyone" },
                ...(users.data ?? [])
                  .filter((user) => user.active)
                  .map((user) => ({ value: user.id, label: <PersonName user={user} />, text: user.name })),
              ]}
            />
          </>
        ) : (
          <span className="rounded bg-elevated px-2 py-1 text-fg-secondary">Your timesheet</span>
        )}
      </div>

      {/* Category strip (spec 59): where the window's time went, whatever the
          grid grouping — categories as first-class facts of the timesheet. */}
      {byCategory.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-subtle/70 px-6 py-2">
          <Tag size={12} className="text-fg-faint" aria-hidden />
          {byCategory.map((row) => (
            <span
              key={row.name}
              className="inline-flex items-center gap-1.5 rounded border border-strong bg-elevated/60 px-2 py-px text-[11px] leading-4 text-fg"
            >
              {row.name}
              <span className="font-semibold text-heading">
                {formatDuration(row.seconds, durationConfig)}
              </span>
            </span>
          ))}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto p-6">
        {timesheet.isPending ? (
          <Spinner label="Loading timesheet…" />
        ) : timesheet.isError ? (
          <QueryError label="the timesheet" error={timesheet.error} />
        ) : rows.length === 0 ? (
          <EmptyState icon={CalendarClock} message="No time logged in this period." />
        ) : (
          <TimesheetGrid
            rows={rows}
            days={days}
            groupBy={groupBy}
            sheet={timesheet.data}
            leave={leaveByUserDay}
          />
        )}
      </div>

      {logging && <LogGeneralTimeModal onClose={() => setLogging(false)} />}
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
}) {
  return (
    <span className="flex items-center gap-1.5 text-fg-muted">
      {label}
      <Select value={value} onChange={onChange} options={options} size="sm" aria-label={label} />
    </span>
  );
}

/** What a drill-down entry shows before the category chip / note (spec 59:
 * itemless entries are named by their scope, never a missing key). */
/** Column header for the grouped axis — a map so adding a grouping is one line
 *  rather than another arm on a nested ternary. */
const GROUP_HEADERS: Record<TimesheetGroupByValue, string> = {
  [TimesheetGroupBy.issue]: "Issue",
  [TimesheetGroupBy.epic]: "Epic",
  [TimesheetGroupBy.category]: "Category",
  [TimesheetGroupBy.person]: "Person",
};

function entryLabel(entry: TimesheetEntry, groupBy: TimesheetGroupByValue): string {
  const where = entry.item
    ? entry.item.key
    : entry.project_key
      ? `${entry.project_key} · no issue`
      : "no issue";
  if (groupBy === TimesheetGroupBy.issue) return entry.user.name;
  if (groupBy === TimesheetGroupBy.person) return where;
  // Grouped by epic, the row is the epic — so each entry names its own issue
  // and author, which is what you drilled in to see.
  if (groupBy === TimesheetGroupBy.epic) return `${entry.user.name} · ${where}`;
  return `${entry.user.name} · ${where}`;
}

/** Log general (itemless) time — spec 59: POST /worklogs, category REQUIRED,
 * anchored to a project or global (no project). Item-bound logging stays on the
 * issue page's time panel. */
function LogGeneralTimeModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const projects = useQuery(projectsQuery());
  const categories = useQuery(workCategoriesQuery());
  const [projectId, setProjectId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [timeSpent, setTimeSpent] = useState("");
  const [workedOn, setWorkedOn] = useState(() => todayIso());
  const [note, setNote] = useState("");

  const save = useMutation({
    mutationFn: () =>
      api.post("/worklogs", {
        project_id: projectId || undefined,
        category_id: categoryId,
        time_spent: timeSpent.trim(),
        worked_on: workedOn,
        note: note.trim(),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["timesheet"] });
      onClose();
    },
  });

  const canSave = categoryId !== "" && timeSpent.trim() !== "";
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (canSave && !save.isPending) save.mutate();
  };

  return (
    <Modal title="Log time — no issue" onClose={onClose}>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <p className="text-xs text-fg-muted">
          Meetings, admin, general work. The category is required — it's how this
          time shows up everywhere. To log against an issue, use the time panel on
          the issue itself.
        </p>
        <SelectField
          label="Category"
          value={categoryId}
          onChange={(event) => setCategoryId(event.target.value)}
        >
          <option value="">Select…</option>
          {(categories.data ?? []).map((category) => (
            <option key={category.id} value={category.id}>
              {category.name}
            </option>
          ))}
        </SelectField>
        <SelectField
          label="Project (optional)"
          value={projectId}
          onChange={(event) => setProjectId(event.target.value)}
          hint="Leave empty for general time not tied to a project"
        >
          <option value="">— No project (general) —</option>
          {(projects.data ?? []).map((project) => (
            <option key={project.id} value={project.id}>
              {project.key} — {project.name}
            </option>
          ))}
        </SelectField>
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Time spent"
            value={timeSpent}
            onChange={(event) => setTimeSpent(event.target.value)}
            placeholder="2h 30m"
            required
          />
          <TextField
            label="Date"
            type="date"
            value={workedOn}
            onChange={(event) => setWorkedOn(event.target.value)}
          />
        </div>
        <TextField
          label="Note (optional)"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Sprint planning, dailies…"
          maxLength={2000}
        />
        {save.isError && (
          <ErrorText error={save.error} />
        )}
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={!canSave || save.isPending}>
            {save.isPending ? "Logging…" : "Log time"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function dayHeader(iso: string): string {
  return formatIso(iso, { weekday: "short", day: "numeric" });
}

/** Weekday key ("mon"…"sun") for an ISO date — matches the /instance work week. */
const WEEKDAY_KEYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"] as const;

function TimesheetGrid({
  rows,
  days,
  groupBy,
  sheet,
  leave,
}: {
  rows: TimesheetRow[];
  days: string[];
  groupBy: TimesheetGroupByValue;
  sheet: Timesheet | undefined;
  /** user id → ISO day → the leave/holiday occupying it. */
  leave: Map<string, Map<string, LeaveCalendarEntry>>;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const { open: openPeek } = usePeek();
  const durationConfig = useDurationConfig();
  // Dim non-working columns (spec 35) — the instance work week.
  const { data: instance } = useQuery(instanceConfigQuery);
  const workingDays = new Set(instance?.work_week_days ?? ["mon", "tue", "wed", "thu", "fri"]);
  const offDay = (day: string) => !workingDays.has(WEEKDAY_KEYS[fromISODate(day).getDay()]);
  const dayClass = (day: string) => (offDay(day) ? " bg-surface/60 opacity-60" : "");
  const columnTotals = days.map((day) => rows.reduce((sum, row) => sum + (row.byDay[day] ?? 0), 0));
  const grandTotal = rows.reduce((sum, row) => sum + row.total, 0);
  const cell = (seconds: number) =>
    seconds > 0 ? formatDuration(seconds, durationConfig) : <span className="text-fg-faint">·</span>;

  // Outlier flags: PERSON view only — a row is one human, so a
  // day cell is one human-day the bounds apply to. Completed days only (an
  // in-progress today always reads under), under-logging only on workdays,
  // and a leave/holiday day is never an outlier.
  const personMode = groupBy === TimesheetGroupBy.person;
  const todayISO = todayIso();
  const minSeconds = (sheet?.day_min_hours ?? 6) * 3600;
  const maxSeconds = (sheet?.day_max_hours ?? 10) * 3600;
  const flagWorkDays = new Set(sheet?.work_days ?? []);
  const personDayCell = (row: TimesheetRow, day: string) => {
    const seconds = row.byDay[day] ?? 0;
    const onLeave = personMode ? leave.get(row.key)?.get(day) : undefined;
    if (onLeave) {
      const kindLabel = onLeave.kind === "holiday" ? "Holiday" : "Leave";
      return {
        className: " opacity-80",
        title: onLeave.label ? `${kindLabel}: ${onLeave.label}` : kindLabel,
        content: (
          <span className="inline-flex items-center justify-end gap-1.5">
            {seconds > 0 && formatDuration(seconds, durationConfig)}
            <AwayChip />
          </span>
        ),
      };
    }
    const done = day < todayISO;
    const workday = flagWorkDays.has(WEEKDAY_KEYS[fromISODate(day).getDay()]);
    if (personMode && done && seconds > maxSeconds) {
      return {
        className: " bg-red-500/10",
        title: `Over-logged: ${formatDuration(seconds, durationConfig)} (max ${sheet?.day_max_hours}h)`,
        content: <span className="font-medium text-red-300">{formatDuration(seconds, durationConfig)}</span>,
      };
    }
    if (personMode && done && workday && seconds < minSeconds) {
      return {
        className: " bg-amber-500/10",
        title: `Under-logged: ${
          seconds > 0 ? formatDuration(seconds, durationConfig) : "nothing"
        } (min ${sheet?.day_min_hours}h)`,
        content:
          seconds > 0 ? (
            <span className="font-medium text-amber-300">
              {formatDuration(seconds, durationConfig)}
            </span>
          ) : (
            <span className="text-amber-300/70">·</span>
          ),
      };
    }
    return { className: "", title: undefined, content: cell(seconds) };
  };

  return (
    <Table>
      <THead>
        <tr>
          <Th className="sticky left-0 z-10 bg-base">
            {GROUP_HEADERS[groupBy]}
          </Th>
          {days.map((day) => (
            <Th key={day} numeric className={dayClass(day)}>
              {dayHeader(day)}
            </Th>
          ))}
          <Th numeric>Total</Th>
        </tr>
      </THead>
      <TBody>
        {rows.map((row) => (
          <Fragment key={row.key}>
            <tr
              onClick={() => setExpanded((current) => (current === row.key ? null : row.key))}
              className="cursor-pointer"
            >
              <Td className="sticky left-0 z-10 max-w-[280px] bg-base">
                <div className="flex items-center gap-2">
                  {row.itemKey ? (
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        openPeek(row.itemKey!);
                      }}
                      className="cursor-pointer font-mono text-xs text-accent-text hover:underline"
                    >
                      {row.label}
                    </button>
                  ) : row.isCategory ? (
                    <span className="inline-flex items-center gap-1 rounded border border-amber-400/30 bg-amber-400/10 px-1.5 py-px text-[11px] leading-4 text-amber-200">
                      <Tag size={10} aria-hidden />
                      {row.label}
                    </span>
                  ) : personMode ? (
                    // The Avatar brings the on-leave dim + palm badge with it.
                    <span className="inline-flex items-center gap-1.5 text-fg">
                      <Avatar user={{ id: row.key, name: row.label }} size="xs" />
                      {row.label}
                    </span>
                  ) : (
                    <span className="text-fg">{row.label}</span>
                  )}
                  {row.sublabel && (
                    <span className="truncate text-fg-muted">{row.sublabel}</span>
                  )}
                </div>
              </Td>
              {days.map((day) => {
                const rendered = personDayCell(row, day);
                return (
                  <Td
                    key={day}
                    numeric
                    className={dayClass(day) + rendered.className}
                    title={rendered.title}
                  >
                    {rendered.content}
                  </Td>
                );
              })}
              <Td numeric className="font-semibold text-heading">
                {formatDuration(row.total, durationConfig)}
              </Td>
            </tr>
            {expanded === row.key &&
              row.entries.map((entry) => (
                <tr key={entry.id} className="bg-surface/40 text-xs">
                  <td className="sticky left-0 z-10 bg-surface/40 px-2 py-1 pl-6 text-fg-secondary">
                    {entryLabel(entry, groupBy)}
                    {entry.category && groupBy !== TimesheetGroupBy.category && (
                      <span className="ml-1.5 rounded bg-elevated px-1 py-px text-[10px] text-amber-200/80">
                        {entry.category.name}
                      </span>
                    )}
                    {entry.external_source && (
                      <span className="ml-1.5">
                        <MirroredBadge source={entry.external_source} />
                      </span>
                    )}
                    {entry.note && <span className="ml-1.5 text-fg-faint">— {entry.note}</span>}
                  </td>
                  {days.map((day) => (
                    <td key={day} className="px-2 py-1 text-right text-fg-muted">
                      {entry.worked_on === day
                        ? formatDuration(entry.time_spent_seconds, durationConfig)
                        : ""}
                    </td>
                  ))}
                  <td className="px-2 py-1 text-right text-fg-secondary">
                    {formatDuration(entry.time_spent_seconds, durationConfig)}
                  </td>
                </tr>
              ))}
          </Fragment>
        ))}
      </TBody>
      <tfoot>
        <tr className="border-t border-strong text-[13px] font-semibold text-fg">
          <td className="sticky left-0 z-10 bg-base px-3 py-2">Total</td>
          {columnTotals.map((total, index) => (
            <td key={days[index]} className="tnum px-3 py-2 text-right">
              {total > 0 ? (
                formatDuration(total, durationConfig)
              ) : (
                <span className="text-fg-faint">·</span>
              )}
            </td>
          ))}
          <td className="tnum px-3 py-2 text-right text-emerald-300">
            {formatDuration(grandTotal, durationConfig)}
          </td>
        </tr>
      </tfoot>
    </Table>
  );
}
