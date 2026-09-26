import { useEffect, useMemo, useReducer, useState } from "react";
import { Callout, CalloutKind, SelectField } from "./host";
import { Button } from "./primitives";
import { shortDateTime, readerTimeZone, browserTimeZone } from "./dates";
import { ScheduleKind, defaultSchedule, type ScheduleConfig, type ScheduleKindValue, type SchedulePreview } from "./schedule";

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

/** Working examples to start from: an empty cron box is where people give up. */
const pillClass = (selected: boolean) =>
  "rounded-full border px-2.5 py-1 text-xs cursor-pointer transition-colors " +
  (selected
    ? "border-accent-hover/60 bg-accent/15 text-accent-text-strong"
    : "border-strong text-fg-secondary hover:border-emphasis hover:text-fg");

const CRON_EXAMPLES: { expression: string; label: string }[] = [
  { expression: "0 9 * * 1", label: "09:00 every Monday" },
  { expression: "0 9 1 * *", label: "09:00 on the 1st of each month" },
  { expression: "0 */4 * * *", label: "Every 4 hours" },
  { expression: "0 8 * * 1-5", label: "08:00 on weekdays" },
  { expression: "30 6 1 1,4,7,10 *", label: "06:30 quarterly" },
];

const timeInputClasses =
  "h-8 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading " +
  "focus:outline-2 focus:outline-offset-1 focus:outline-focus";


export interface ScheduleEditorProps {
  value: ScheduleConfig;
  onChange: (schedule: ScheduleConfig) => void;
  previewSchedule: (schedule: ScheduleConfig, signal: AbortSignal) => Promise<SchedulePreview>;
}

/** A preview belongs to one draft and mount. Never display a previous draft's
 * response while debouncing, and stop the transport when replaced or withdrawn. */
function useSchedulePreview(value: ScheduleConfig, fetchPreview: ScheduleEditorProps["previewSchedule"]) {
  const key = JSON.stringify(value);
  const [attempt, retry] = useReducer((n: number) => n + 1, 0);
  // An A → B → A edit must not resurrect the first A response.
  const identity = useMemo(() => ({key, attempt, fetchPreview}), [key, attempt, fetchPreview]);
  const [result, setResult] = useState<{identity: typeof identity; preview?: SchedulePreview; failed?: boolean} | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void fetchPreview(JSON.parse(key), controller.signal).then(preview => {
        if (!controller.signal.aborted) setResult({identity, preview});
      }).catch(() => {
        if (!controller.signal.aborted) setResult({identity, failed: true});
      });
    }, 350);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [identity, key, fetchPreview]);
  const current = result?.identity === identity ? result : null;
  return {preview: current?.preview, failed: current?.failed, pending: !current, retry};
}

/** Controlled scheduling inputs. Owners provide transport and contextual help. */
export function ScheduleEditor({value, onChange, previewSchedule}: ScheduleEditorProps) {
  const {preview, failed, pending, retry} = useSchedulePreview(value, previewSchedule);
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
          {!Object.values(ScheduleKind).includes(value.kind) && <option value={value.kind}>{value.kind} (unavailable)</option>}
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
            {!INTERVAL_PRESETS.some(preset => preset.minutes === (value.minutes ?? 60)) && (
              <option value={String(value.minutes)}>Every {value.minutes} minutes (saved interval)</option>
            )}
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
          <span className="font-normal text-[11px] text-fg-secondary">
            Months without that day use their last one — the 31st runs on 28 February.
          </span>
        </label>
      )}

      {value.kind === ScheduleKind.cron && (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-secondary">Start from</span>
          <div className="flex flex-wrap gap-1.5">
            {CRON_EXAMPLES.map((example) => (
              <Button variant="ghost" size="sm"
                key={example.expression}
                type="button"
                onClick={() => onChange({ ...value, expression: example.expression })}
                aria-pressed={value.expression === example.expression}
                title={example.expression}
                className={pillClass(value.expression === example.expression)}
              >
                {example.label}
              </Button>
            ))}
          </div>
          <span className="text-[11px] text-fg-secondary">
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
                <Button variant="ghost" size="sm"
                  key={name}
                  type="button"
                  onClick={() => toggleWeekday(day)}
                  aria-pressed={selected}
                  className={pillClass(selected)}
                >
                  {name}
                </Button>
              );
            })}
          </div>
        </div>
      )}

      {/* What this schedule actually does. It is the only readable form of a cron
          expression, and it is where the monthly clamp becomes visible: the 31st
          previews as 31 Aug, 30 Sep, 31 Oct rather than needing a paragraph. */}
      {pending && <p role="status" className="text-xs text-fg-secondary">Checking next runs…</p>}
      {failed && <div role="status" className="flex items-center gap-2 text-xs text-fg-secondary">
        Preview unavailable. Your schedule is preserved.
        <Button variant="ghost" size="sm" onClick={retry}>Retry preview</Button>
      </div>}
      {preview?.error ? (
        <Callout kind={CalloutKind.danger}>{preview.error}</Callout>
      ) : preview && preview.next_runs.length > 0 ? (
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-fg-secondary">Next runs</span>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-fg-secondary">
            {preview.next_runs.map((iso) => (
              <span key={iso}>{shortDateTime(iso)}</span>
            ))}
          </div>
        </div>
      ) : null}

      <p className="text-[11px] text-fg-secondary">
        {preview ? `Schedule timezone: ${preview.timezone}. Next runs are displayed in your timezone (${readerTimeZone() || browserTimeZone()}).` : "Times use the server's scheduler timezone."}
      </p>
    </div>
  );
}
