import { useState } from "react";
import { parseDuration } from "./model";

/**
 * Type a duration, press Enter, it is logged (RADD-1573) — the gesture the
 * reference tool is used for most. Takes what `parseDuration` reads: `1`,
 * `1.5`, `1h 30m`, `90m`, `1:30`. Something unreadable stays in the field,
 * marked, instead of logging a guess.
 */
export function QuickLogField({
  subject,
  day,
  disabled,
  onLog,
}: {
  /** What the time goes on, for the label: an issue key. */
  subject: string;
  /** The day it goes on, in words. */
  day: string;
  disabled?: boolean;
  onLog: (seconds: number) => void;
}) {
  const [text, setText] = useState("");
  const [bad, setBad] = useState(false);
  return (
    <input
      value={text}
      disabled={disabled}
      inputMode="decimal"
      placeholder="1h"
      data-quick-log={subject}
      aria-label={`Time to log on ${subject} for ${day}`}
      aria-invalid={bad || undefined}
      title={
        bad
          ? "Not a duration. Try 1, 1.5, 1h 30m or 1:30"
          : `Type a duration and press Enter to log it on ${day}`
      }
      onChange={(event) => {
        setText(event.target.value);
        setBad(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          setText("");
          setBad(false);
        }
        if (event.key !== "Enter" || !text.trim()) return;
        const seconds = parseDuration(text);
        if (seconds === null || seconds <= 0) {
          setBad(true);
          return;
        }
        onLog(seconds);
        setText("");
      }}
      className={`w-14 shrink-0 rounded border bg-base px-1.5 py-0.5 text-right text-meta tabular-nums text-fg outline-focus placeholder:text-fg-faint focus-visible:outline-2 disabled:cursor-not-allowed disabled:opacity-60 ${
        bad ? "border-status-danger-ink" : "border-strong"
      }`}
    />
  );
}
