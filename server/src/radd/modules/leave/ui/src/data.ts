import { api, type DataSource, type PersonIndicator, type StatusIndicator, type TimesheetAnnotation, shiftIsoDay, shortDate } from "@radd/plugin-sdk";
import { dayNote, hm, isTimed, readerZone } from "./format";
import type { Kind } from "./types";

interface Current { user_id: string; label: string; until: string; until_time?: string | null; timezone?: string }
interface Calendar { user_id: string; label: string; kind: Kind; start_date: string; end_date: string; start_time?: string | null; end_time?: string | null; timezone?: string }
const badge: StatusIndicator = { id: "leave", label: "away", ariaLabel: "On leave", title: "", tone: "warning", dim: true, textSuffix: "🌴" };

const zoneSuffix = (zone: string | undefined, timed: boolean) => (timed && zone && zone !== readerZone() ? ` ${zone}` : "");

function* days(from: string, to: string): Generator<string> {
  for (let day = from; day <= to; day = shiftIsoDay(day, 1)) yield day;
}

/** A whole-day span is one annotation the host spreads over its days; a timed span becomes one
 *  per day so the boundary cells can say "from 12:00" / "until 16:00" (RADD-1481). */
function annotate(p: Calendar, index: number): TimesheetAnnotation[] {
  const base = `${p.kind === "holiday" ? "Holiday" : "Leave"}${p.label ? `: ${p.label}` : ""}`;
  const common = { ...badge, personId: p.user_id, suppressOutlier: true };
  if (!isTimed(p)) return [{ ...common, id: `${index}`, start: p.start_date, end: p.end_date, title: base }];
  return Array.from(days(p.start_date, p.end_date), day => {
    const note = dayNote(p, day);
    return { ...common, id: `${index}:${day}`, start: day, end: day, title: note ? `${base}, ${note}${zoneSuffix(p.timezone, true)}` : base };
  });
}

export const leaveDataSources: DataSource[] = [
  {
    kind: "personIndicators", id: "current", staleTime: 300_000, refetchInterval: 300_000,
    async fetch(_args, signal): Promise<PersonIndicator[]> {
      const periods = await api.get<Current[]>("/leave/current", { signal });
      return periods.map(p => ({
        ...badge, personId: p.user_id,
        title: `on leave until ${shortDate(p.until)}${p.until_time ? `, ${hm(p.until_time)}` : ""}${zoneSuffix(p.timezone, Boolean(p.until_time))}${p.label ? ` (${p.label})` : ""}`,
      }));
    },
  },
  {
    kind: "timesheetAnnotations", id: "calendar",
    async fetch({ start, end }, signal): Promise<TimesheetAnnotation[]> {
      const periods = await api.get<Calendar[]>("/leave/calendar", { signal, query: { start, end } });
      return periods.flatMap(annotate);
    },
  },
];
