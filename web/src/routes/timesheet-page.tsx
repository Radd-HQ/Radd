import { useState } from "react";
import { todayIso } from "@radd/plugin-sdk";
import { TimeLogCalendar } from "../components/timelog/TimeLogCalendar";
import { readUrlState, writeUrlState } from "../lib/url-state";
import { TimesheetReport } from "./timesheet";

const Mode = { log: "log", report: "report" } as const;
type ModeValue = (typeof Mode)[keyof typeof Mode];

const MODES: { value: ModeValue; label: string }[] = [
  { value: Mode.log, label: "My week" },
  { value: Mode.report, label: "Report" },
];

/**
 * /timesheet — two surfaces over the same worklogs (RADD-1541).
 *
 * **My week** is for ENTERING time: one person's week as a calendar of cards.
 * **Report** is for READING it: the grid across people, periods and groupings
 * the page has always been. They were one screen, built for reading, and people
 * logged time issue by issue; the split is what the pilot asked for.
 *
 * Which one is open lives in the URL (`m`), so a link or a refresh lands where
 * it was sent. The calendar is the default: logging is the daily act, a report
 * the weekly one.
 */
export function TimesheetPage() {
  const url = readUrlState();
  // A link that carries the report's own state — a grouping, a period, a
  // project, team or person filter, a query — was made on the report and opens
  // it, whether or not it says so: every timesheet link from before the split.
  const reportLink = Boolean(url.g || url.p || url.pr || url.tm || url.u || url.q);
  const [mode, setModeState] = useState<ModeValue>(
    url.m === Mode.report || (!url.m && reportLink) ? Mode.report : Mode.log,
  );
  const [anchor, setAnchorState] = useState(url.d ?? todayIso());
  const setMode = (value: ModeValue) => {
    setModeState(value);
    writeUrlState({ m: value === Mode.log ? null : value });
  };
  const setAnchor = (value: string) => {
    setAnchorState(value);
    writeUrlState({ d: value });
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-3 border-b border-subtle px-6 pt-3">
        <div role="tablist" aria-label="Timesheet" className="flex gap-1">
          {MODES.map((option) => (
            <button
              key={option.value}
              type="button"
              role="tab"
              aria-selected={mode === option.value}
              data-timesheet-mode={option.value}
              onClick={() => setMode(option.value)}
              className={`-mb-px border-b-2 px-3 pb-2 text-row cursor-pointer ${
                mode === option.value
                  ? "border-accent font-medium text-heading"
                  : "border-transparent text-fg-secondary hover:text-fg"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
      {mode === Mode.log ? (
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          <TimeLogCalendar anchor={anchor} onAnchor={setAnchor} />
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <TimesheetReport />
        </div>
      )}
    </div>
  );
}
