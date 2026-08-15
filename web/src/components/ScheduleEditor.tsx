import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { Callout, CalloutKind } from "./Callout";
import { shortDateTime } from "../lib/dates";
import {
  ScheduleKind,
  type RuleSchedule,
  type SchedulePreview,
  type ScheduleKindValue,
} from "../lib/types";
import { SelectField } from "./SelectField";

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
  [ScheduleKind.monthly]: "Monthly",
  [ScheduleKind.cron]: "Custom (cron)",
};

/** A few expressions worth starting from. Cron is powerful and unreadable, and
 * an empty box is where people give up — a working example they can edit is
 * the difference between the feature existing and being used. */
const CRON_EXAMPLES: { expression: string; label: string }[] = [
  { expression: "0 9 * * 1", label: "09:00 every Monday" },
  { expression: "0 9 1 * *", label: "09:00 on the 1st of each month" },
  { expression: "0 */4 * * *", label: "Every 4 hours" },
  { expression: "0 8 * * 1-5", label: "08:00 on weekdays" },
  { expression: "30 6 1 1,4,7,10 *", label: "06:30 quarterly" },
];

export function defaultSchedule(kind: ScheduleKindValue): RuleSchedule {
  switch (kind) {
    case ScheduleKind.interval:
      return { kind, minutes: 60 };
    case ScheduleKind.daily:
      return { kind, time: "09:00" };
    case ScheduleKind.monthly:
      // The 1st, because "monthly" almost always means the start of the month
      // and the alternative is asking someone to pick a number before they have
      // said what they want.
      return { kind, time: "09:00", day: 1 };
    case ScheduleKind.cron:
      return { kind, expression: "0 9 * * 1" };
    default:
      return { kind, time: "09:00", weekdays: [0] };
  }
}

/** A schedule the API will accept: interval has minutes; daily/weekly have a
 * time; weekly has at least one weekday. */
export function isScheduleValid(schedule: RuleSchedule): boolean {
  if (schedule.kind === ScheduleKind.interval) return Boolean(schedule.minutes);
  // Only a shape check — whether the expression PARSES, and whether it fires
  // more often than the floor allows, is the server's answer. A second cron
  // parser in the browser would be a second thing to be wrong.
  if (schedule.kind === ScheduleKind.cron) return Boolean(schedule.expression?.trim());
  if (!schedule.time) return false;
  if (schedule.kind === ScheduleKind.monthly) {
    const day = schedule.day ?? 0;
    return day >= 1 && day <= 31;
  }
  return schedule.kind !== ScheduleKind.weekly || (schedule.weekdays?.length ?? 0) > 0;
}

const timeInputClasses =
  "h-8 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading " +
  "focus:outline-2 focus:outline-offset-1 focus:outline-focus [color-scheme:dark]";


/** Debounce before asking the server, so typing a cron expression character by
 * character does not fire six requests and settle on whichever answers last. */
const PREVIEW_DEBOUNCE_MS = 350;

/** When this schedule would actually run, straight from the engine's own math.
 *
 * Not computed here. A cron parser in the browser would be a second thing to be
 * wrong, and the preview's whole value is that it agrees with what the server
 * will do — including the refusals, which arrive as `error` and are shown before
 * the form is saved rather than as a 409 afterwards.
 */
function useSchedulePreview(schedule: RuleSchedule): SchedulePreview | null {
  const [preview, setPreview] = useState<SchedulePreview | null>(null);
  const key = JSON.stringify(schedule);

  useEffect(() => {
    let live = true;
    const timer = setTimeout(() => {
      api
        .post<SchedulePreview>("/automations/schedule/preview", JSON.parse(key))
        .then((result) => {
          if (live) setPreview(result);
        })
        .catch(() => {
          // A failed preview is not a failed form — it stays silent and the save
          // path keeps its own validation.
          if (live) setPreview(null);
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [key]);

  return preview;
}

/** The schedule editor, shared by automations and backups (RADD-912).
 *
 * It lives here rather than under `automations/` because both features store the
 * same config and validate it through the same rules on the server. Backups
 * previously hardcoded "daily", so monthly and cron were reachable through the
 * API and invisible in the product — which is the same shape of gap that had
 * a studio file a request for scheduling that already half-existed. */
export function ScheduleEditor({
  value,
  onChange,
}: {
  value: RuleSchedule;
  onChange: (schedule: RuleSchedule) => void;
}) {
  const preview = useSchedulePreview(value);

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
        ) : value.kind === ScheduleKind.cron ? (
          <label className="flex flex-col gap-1.5 text-xs font-medium text-fg-secondary">
            Expression
            <input
              type="text"
              value={value.expression ?? ""}
              onChange={(event) => onChange({ ...value, expression: event.target.value })}
              placeholder="0 9 * * 1"
              spellCheck={false}
              className={timeInputClasses + " font-mono"}
              aria-label="Cron expression"
            />
          </label>
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

      {value.kind === ScheduleKind.monthly && (
        <label className="flex w-fit flex-col gap-1.5 text-xs font-medium text-fg-secondary">
          On day
          <input
            type="number"
            min={1}
            max={31}
            value={value.day ?? 1}
            onChange={(event) => onChange({ ...value, day: Number(event.target.value) })}
            className={timeInputClasses + " w-24"}
            aria-label="Day of the month"
          />
          <span className="font-normal text-[11px] text-fg-faint">
            Months without that day use their last one — the 31st runs on 28 February.
          </span>
        </label>
      )}

      {value.kind === ScheduleKind.cron && (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-secondary">Start from</span>
          <div className="flex flex-wrap gap-1.5">
            {CRON_EXAMPLES.map((example) => (
              <button
                key={example.expression}
                type="button"
                onClick={() => onChange({ ...value, expression: example.expression })}
                aria-pressed={value.expression === example.expression}
                title={example.expression}
                className={
                  "rounded-full border px-2.5 py-1 text-xs cursor-pointer transition-colors " +
                  (value.expression === example.expression
                    ? "border-accent-hover/60 bg-accent/15 text-accent-text-strong"
                    : "border-strong text-fg-secondary hover:border-emphasis hover:text-fg")
                }
              >
                {example.label}
              </button>
            ))}
          </div>
          <span className="text-[11px] text-fg-faint">
            Five fields: minute, hour, day of month, month, day of week. It cannot run more
            often than every 5 minutes.
          </span>
        </div>
      )}
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

      {/* What this schedule actually does. It is the only readable form of a cron
          expression, and it is where the monthly clamp becomes visible: the 31st
          previews as 31 Aug, 30 Sep, 31 Oct rather than needing a paragraph. */}
      {preview?.error ? (
        <Callout kind={CalloutKind.danger}>{preview.error}</Callout>
      ) : preview && preview.next_runs.length > 0 ? (
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-fg-secondary">Next runs</span>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-fg-muted">
            {preview.next_runs.map((iso) => (
              <span key={iso}>{shortDateTime(iso)}</span>
            ))}
          </div>
        </div>
      ) : null}

      <p className="text-[11px] text-fg-faint">
        Times run on the server's scheduler timezone (one instance clock).{" "}
        <strong className="font-medium text-fg-secondary">
          A schedule can create issues:
        </strong>{" "}
        add a <em>Create item</em> action and it runs once per occurrence — recurring maintenance
        tickets, periodic reviews, and the like. With a filter, item actions apply to every issue
        it matches (max 200, rank order).
      </p>
    </div>
  );
}
