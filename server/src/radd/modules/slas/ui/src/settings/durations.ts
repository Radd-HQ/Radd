/** Durations and daily windows as the policy form reads and writes them. */

/** "1d", "8h", "90m" — the shortest exact reading of a target in minutes; null → "—". */
export function minutesLabel(minutes: number | null): string {
  if (minutes === null) return "—";
  if (minutes % (24 * 60) === 0) return `${minutes / (24 * 60)}d`;
  if (minutes % 60 === 0) return `${minutes / 60}h`;
  return `${minutes}m`;
}

const hhmm = (minutes: number) =>
  `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;

/** "09:00–17:30" for a policy's business window; null when it has none. */
export function windowLabel(startMinute: number | null, endMinute: number | null): string | null {
  if (startMinute === null || endMinute === null) return null;
  return `${hhmm(startMinute)}–${hhmm(endMinute)}`;
}

/** Minutes → the text the duration fields take ("1h", "90m", "2d"); null → "". */
export function durationText(minutes: number | null): string {
  return minutes === null ? "" : minutesLabel(minutes);
}

/** Minutes from midnight → "HH:MM" for an <input type="time">; null → "". */
export function minutesToTime(minutes: number | null): string {
  return minutes === null ? "" : hhmm(minutes);
}

/** "HH:MM" (from an <input type="time">) → minutes from midnight; "" → null. */
export function timeToMinutes(value: string): number | null {
  if (!value) return null;
  const [hours, minutes] = value.split(":").map(Number);
  return hours * 60 + minutes;
}

/**
 * RADD-1288: a clock duration typed the way people say it — "90", "90m",
 * "1h 30m", "8h", "2d" (a day here is 24 clock hours, as SLA targets count) —
 * as whole minutes. Empty → null; anything else unparseable → NaN.
 */
export function parseClockMinutes(text: string): number | null {
  const raw = text.trim().toLowerCase();
  if (!raw) return null;
  if (/^\d+$/.test(raw)) return Number(raw);
  const units: Record<string, number> = { d: 24 * 60, h: 60, m: 1 };
  let total = 0;
  let rest = raw.replace(/\s+/g, "");
  const part = /^(\d+(?:\.\d+)?)([dhm])/;
  if (!part.test(rest)) return Number.NaN;
  while (rest) {
    const match = part.exec(rest);
    if (!match) return Number.NaN;
    total += Number(match[1]) * units[match[2]];
    rest = rest.slice(match[0].length);
  }
  return Math.round(total);
}
