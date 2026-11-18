import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { formatIso, todayIso } from "./dates";
import { addDays, addMonths, inRange, monthGrid, weekdayIndex } from "./date-math";

const WIDTH_PX = 264;
const HEIGHT_PX = 318;
const GAP_PX = 4;

const WEEKDAYS = Array.from({ length: 7 }, (_, index) => {
  // 2024-01-01 is a Monday.
  const iso = addDays("2024-01-01", index);
  return { short: formatIso(iso, { weekday: "narrow" }), long: formatIso(iso, { weekday: "long" }) };
});

const navButton =
  "flex size-7 items-center justify-center rounded text-fg-secondary hover:bg-elevated hover:text-heading " +
  "focus-visible:outline-2 focus-visible:outline-focus cursor-pointer";
const footButton =
  "rounded px-2 py-1 text-meta text-accent-text hover:bg-elevated hover:text-accent-text-strong " +
  "focus-visible:outline-2 focus-visible:outline-focus cursor-pointer disabled:cursor-not-allowed disabled:text-fg-faint";

/**
 * The month grid behind every date field (RADD-1566): drawn by the app, so it
 * is the same calendar in every browser and follows the app's tokens.
 *
 * It floats on the document body, fixed to its anchor: a date field inside a
 * scrolling modal or a dense table row would otherwise have its calendar cut
 * off by that container. It opens under the field and above it when there is
 * no room below.
 *
 * Keys, on the grid: arrows move a day or a week, Home and End go to the ends
 * of the week, PageUp and PageDown move a month (with Shift, a year), Enter or
 * Space picks, Escape closes. Days outside `min`..`max` can be moved over but
 * not picked.
 */
export function CalendarPopover({
  anchor,
  value,
  min,
  max,
  label,
  focusGrid,
  onPick,
  onClose,
}: {
  anchor: HTMLElement;
  value: string;
  min?: string;
  max?: string;
  label: string;
  /** Move focus into the grid on open (keyboard open), or leave it in the field. */
  focusGrid: boolean;
  onPick: (iso: string) => void;
  /** `refocus`: put focus back on the field (Escape, Tab, a pick). */
  onClose: (refocus: boolean) => void;
}) {
  const today = todayIso();
  const [cursor, setCursor] = useState(value || (inRange(today, min, max) ? today : (min ?? max ?? today)));
  const [place, setPlace] = useState<{ left: number; top: number } | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const wantFocus = useRef(focusGrid);

  useLayoutEffect(() => {
    const position = () => {
      const rect = anchor.getBoundingClientRect();
      const below = window.innerHeight - rect.bottom;
      const top = below < HEIGHT_PX + GAP_PX && rect.top > below ? rect.top - HEIGHT_PX - GAP_PX : rect.bottom + GAP_PX;
      const left = Math.max(8, Math.min(rect.left, window.innerWidth - WIDTH_PX - 8));
      setPlace({ left, top: Math.max(8, top) });
    };
    position();
    // Capture: a scroll in ANY ancestor moves the field.
    window.addEventListener("scroll", position, true);
    window.addEventListener("resize", position);
    return () => {
      window.removeEventListener("scroll", position, true);
      window.removeEventListener("resize", position);
    };
  }, [anchor]);

  useEffect(() => {
    const outside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!panel.current?.contains(target) && !anchor.contains(target)) onClose(false);
    };
    document.addEventListener("pointerdown", outside, true);
    return () => document.removeEventListener("pointerdown", outside, true);
  }, [anchor, onClose]);

  // Roving focus: the cursor's day is the grid's one tab stop.
  useEffect(() => {
    if (!wantFocus.current || !place) return;
    panel.current?.querySelector<HTMLElement>(`[data-day="${cursor}"]`)?.focus();
  }, [cursor, place]);

  const move = (to: string) => {
    wantFocus.current = true;
    setCursor(to);
  };
  const pick = (iso: string) => {
    if (!inRange(iso, min, max)) return;
    onPick(iso);
    onClose(true);
  };
  const onKeyDown = (event: ReactKeyboardEvent) => {
    const steps: Record<string, () => string> = {
      ArrowLeft: () => addDays(cursor, -1),
      ArrowRight: () => addDays(cursor, 1),
      ArrowUp: () => addDays(cursor, -7),
      ArrowDown: () => addDays(cursor, 7),
      Home: () => addDays(cursor, -weekdayIndex(cursor)),
      End: () => addDays(cursor, 6 - weekdayIndex(cursor)),
      PageUp: () => addMonths(cursor, event.shiftKey ? -12 : -1),
      PageDown: () => addMonths(cursor, event.shiftKey ? 12 : 1),
    };
    if (event.key === "Escape" || event.key === "Tab") {
      // Stopped here so the dialog underneath does not also close, and so its
      // focus trap does not treat the floating panel as "outside".
      event.preventDefault();
      event.stopPropagation();
      onClose(true);
      return;
    }
    const step = steps[event.key];
    if (!step || !(event.target as HTMLElement).hasAttribute("data-day")) return;
    event.preventDefault();
    move(step());
  };

  if (!place) return null;
  const month = cursor.slice(0, 7);
  const monthLabel = formatIso(`${month}-01`, { month: "long", year: "numeric" });
  return createPortal(
    <div
      ref={panel}
      role="dialog"
      aria-label={`${label}: choose a date`}
      data-date-calendar
      onKeyDown={onKeyDown}
      style={{ left: place.left, top: place.top, width: WIDTH_PX }}
      className="fixed z-[70] rounded-lg border border-subtle bg-surface p-2 shadow-pop animate-menu-in"
    >
      <div className="flex items-center gap-1 pb-1.5">
        <button type="button" className={navButton} aria-label="Previous month" onClick={() => setCursor(addMonths(cursor, -1))}>
          <ChevronLeft size={15} aria-hidden />
        </button>
        <span className="flex-1 text-center text-row font-semibold text-heading" aria-live="polite" data-calendar-month>
          {monthLabel}
        </span>
        <button type="button" className={navButton} aria-label="Next month" onClick={() => setCursor(addMonths(cursor, 1))}>
          <ChevronRight size={15} aria-hidden />
        </button>
      </div>
      <table role="grid" className="w-full border-collapse" aria-label={monthLabel}>
        <thead>
          <tr>
            {WEEKDAYS.map((day) => (
              <th key={day.long} scope="col" abbr={day.long} className="h-7 w-[14.28%] text-center text-meta font-medium text-fg-secondary">
                {day.short}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {monthGrid(cursor).map((week) => (
            <tr key={week[0]}>
              {week.map((iso) => {
                const selected = iso === value;
                const allowed = inRange(iso, min, max);
                const tone = selected
                  // Accent as legible text on a tint, ringed: white on the accent fill is 4.3:1 in light.
                  ? "bg-accent/20 text-accent-text-strong font-semibold ring-1 ring-inset ring-accent "
                  : !allowed
                    ? "text-fg-faint line-through cursor-not-allowed "
                    : iso.slice(0, 7) === month
                      ? "text-heading hover:bg-elevated "
                      : "text-fg-secondary hover:bg-elevated ";
                return (
                  <td key={iso} role="gridcell" aria-selected={selected} className="p-0 text-center">
                    <button
                      type="button"
                      data-day={iso}
                      tabIndex={iso === cursor ? 0 : -1}
                      aria-label={formatIso(iso, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}
                      aria-current={iso === today ? "date" : undefined}
                      aria-disabled={!allowed || undefined}
                      onClick={() => pick(iso)}
                      onFocus={() => setCursor(iso)}
                      className={
                        "size-8 rounded-md text-row tabular-nums focus-visible:outline-2 focus-visible:outline-focus " +
                        (allowed ? "cursor-pointer " : "") +
                        tone +
                        (iso === today && !selected ? "border border-emphasis font-semibold " : "")
                      }
                    >
                      {Number(iso.slice(8))}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex items-center justify-between border-t border-subtle pt-1.5 mt-1.5">
        <button type="button" className={footButton} disabled={!inRange(today, min, max)} onClick={() => pick(today)}>
          Today
        </button>
        <button
          type="button"
          className={footButton}
          disabled={!value}
          onClick={() => {
            onPick("");
            onClose(true);
          }}
        >
          Clear
        </button>
      </div>
    </div>,
    document.body,
  );
}
