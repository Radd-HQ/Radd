import { api, type DataSource, type PersonIndicator, type StatusIndicator, type TimesheetAnnotation, shortDate } from "@radd/plugin-sdk";
interface Current { user_id: string; label: string; until: string }
interface Calendar { user_id: string; label: string; kind: "leave" | "holiday"; start_date: string; end_date: string }
const badge: StatusIndicator = { id: "leave", label: "away", ariaLabel: "On leave", title: "", tone: "warning", dim: true, textSuffix: "🌴" };

export const leaveDataSources: DataSource[] = [
  {
    kind: "personIndicators", id: "current", staleTime: 300_000, refetchInterval: 300_000,
    async fetch(_args, signal): Promise<PersonIndicator[]> {
      const periods = await api.get<Current[]>("/leave/current", { signal });
      return periods.map(p => ({ ...badge, personId: p.user_id, title: `on leave until ${shortDate(p.until)}${p.label ? ` (${p.label})` : ""}` }));
    },
  },
  {
    kind: "timesheetAnnotations", id: "calendar",
    async fetch({ start, end }, signal): Promise<TimesheetAnnotation[]> {
      const periods = await api.get<Calendar[]>("/leave/calendar", { signal, query: { start, end } });
      return periods.map(p => ({ ...badge, personId: p.user_id, start: p.start_date, end: p.end_date, suppressOutlier: true, title: `${p.kind === "holiday" ? "Holiday" : "Leave"}${p.label ? `: ${p.label}` : ""}` }));
    },
  },
];
