# Spec 35 — Work week + business-day SLA timers

Studios don't all run Mon–Fri, and SLA clocks that tick through weekends breach
Friday-evening tickets by Monday. This spec adds an instance-level work week and
lets SLA policies count only working days.

- **`RADD_WORK_WEEK_DAYS`** (default `mon,tue,wed,thu,fri`) — comma-separated day
  names. Exposed to authenticated clients at **`GET /instance`**
  (`{work_week_days: [...]}`) so the frontend renders the same calendar.
- **SLA**: policies gain **`work_week_only`** — when set, every non-working day
  becomes a midnight-to-midnight pause interval merged into the existing pause
  machinery (`timers.non_working_pauses`, pure + tested: a Friday-10:00 ticket
  with a 24 h target comes due Monday 10:00). Settings-page checkbox + "work
  week only" in the policy summary.
- **Timesheet**: non-working day columns render dimmed.
- Parsing is defensive: unknown names ignored, empty/garbage falls back to
  Mon–Fri (a zero-day week would float every deadline forever).

## Known simplifications

- Instance-level only (per-workspace work weeks later); days are naive-UTC
  midnights, matching event timestamps — half-day/holiday calendars and
  hour-of-day windows (9–18) are future work.
- `timelog_days_per_week` (duration parsing) remains an independent number; keep
  the two settings consistent by hand.
