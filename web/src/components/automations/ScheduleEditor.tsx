import { ScheduleKind, type RuleSchedule, type ScheduleKindValue } from "../../lib/types";
import { SelectField } from "../SelectField";

/** Preset interval choices (minutes) — the spec-69 minutes/hours select. */
const INTERVAL_PRESETS: { minutes: number; label: string }[] = [
  { minutes: 5, label: "Every 5 minutes" },
  { minutes: 15, label: "Every 15 minutes" },
  { minutes: 30, label: "Every 30 minutes" },
  { minutes: 60, label: "Every hour" },
  { minutes: 120, label: "Every 2 hours" },
  { minutes: 240, label: "Every 4 hours" },
  { minutes: 480, label: "Every 8 hours" },
  { minutes: 720, label: "Every 12 hours" },
  { minutes: 1440, label: "Every 24 hours" },
];

/** Mon-first, matching the backend's 0=Mon convention. */
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const KIND_LABELS: Record<ScheduleKindValue, string> = {
  [ScheduleKind.interval]: "At an interval",
  [ScheduleKind.daily]: "Daily",
  [ScheduleKind.weekly]: "Weekly",
};

export function defaultSchedule(kind: ScheduleKindValue): RuleSchedule {
  switch (kind) {
    case ScheduleKind.interval:
      return { kind, minutes: 60 };
    case ScheduleKind.daily:
      return { kind, time: "09:00" };
    default:
      return { kind, time: "09:00", weekdays: [0] };
  }
}

/** A schedule the API will accept: interval has minutes; daily/weekly have a
 * time; weekly has at least one weekday. */
export function isScheduleValid(schedule: RuleSchedule): boolean {
  if (schedule.kind === ScheduleKind.interval) return Boolean(schedule.minutes);
  if (!schedule.time) return false;
  return schedule.kind !== ScheduleKind.weekly || (schedule.weekdays?.length ?? 0) > 0;
}

const timeInputClasses =
  "h-8 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading " +
  "focus:outline-2 focus:outline-offset-1 focus:outline-focus [color-scheme:dark]";

/** Editor for a scheduled rule's `schedule` (spec 69): interval preset, or a
 * daily/weekly wall-clock time with weekday toggles. One instance clock —
 * times run in the server's scheduler timezone. */
export function ScheduleEditor({
  value,
  onChange,
}: {
  value: RuleSchedule;
  onChange: (schedule: RuleSchedule) => void;
}) {
  const toggleWeekday = (day: number) => {
    const current = value.weekdays ?? [];
    const next = current.includes(day)
      ? current.filter((entry) => entry !== day)
      : [...current, day].sort((a, b) => a - b);
    onChange({ ...value, weekdays: next });
  };

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-subtle p-4">
      <div className="grid grid-cols-2 gap-3">
        <SelectField
          label="Repeats"
          value={value.kind}
          onChange={(event) => onChange(defaultSchedule(event.target.value as ScheduleKindValue))}
        >
          {(Object.values(ScheduleKind) as ScheduleKindValue[]).map((kind) => (
            <option key={kind} value={kind}>
              {KIND_LABELS[kind]}
            </option>
          ))}
        </SelectField>
        {value.kind === ScheduleKind.interval ? (
          <SelectField
            label="Interval"
            value={String(value.minutes ?? 60)}
            onChange={(event) =>
              onChange({ ...value, minutes: Number(event.target.value) })
            }
          >
            {INTERVAL_PRESETS.map((preset) => (
              <option key={preset.minutes} value={preset.minutes}>
                {preset.label}
              </option>
            ))}
          </SelectField>
        ) : (
          <label className="flex flex-col gap-1.5 text-xs font-medium text-fg-secondary">
            At
            <input
              type="time"
              value={value.time ?? ""}
              onChange={(event) => onChange({ ...value, time: event.target.value })}
              className={timeInputClasses}
              aria-label="Run time"
            />
          </label>
        )}
      </div>
      {value.kind === ScheduleKind.weekly && (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-secondary">On</span>
          <div className="flex flex-wrap gap-1.5">
            {WEEKDAYS.map((name, day) => {
              const selected = (value.weekdays ?? []).includes(day);
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => toggleWeekday(day)}
                  aria-pressed={selected}
                  className={
                    "rounded-full border px-2.5 py-1 text-xs cursor-pointer transition-colors " +
                    (selected
                      ? "border-accent-hover/60 bg-accent/15 text-accent-text-strong"
                      : "border-strong text-fg-secondary hover:border-emphasis hover:text-fg")
                  }
                >
                  {name}
                </button>
              );
            })}
          </div>
        </div>
      )}
      <p className="text-[11px] text-fg-faint">
        Times run on the server's scheduler timezone (one instance clock). Each run applies the
        item actions to every item matching the SLQ filter below (max 200, rank order); create
        item / webhook / chat / notify / email actions run once per occurrence.
      </p>
    </div>
  );
}
