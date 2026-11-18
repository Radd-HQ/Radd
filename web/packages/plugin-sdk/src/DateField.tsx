import { useCallback, useId, useMemo, useRef, useState, type ChangeEvent, type InputHTMLAttributes } from "react";
import { CalendarDays } from "lucide-react";
import { CalendarPopover } from "./date-calendar";
import { formatIso } from "./dates";
import { inRange, isIsoDate, localeDateOrder, localeMonthNames, parseTypedDate } from "./date-math";

const fieldClasses =
  "flex h-8 items-center rounded-md border bg-surface text-row text-heading " +
  "focus-within:outline-2 focus-within:outline-offset-1 focus-within:outline-focus ";

type DateInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "value" | "min" | "max"> & {
  /** An ISO date ("2026-11-17") or "". */
  value?: string | null;
  min?: string;
  max?: string;
  /** Red border, for a field whose value was refused. */
  invalid?: boolean;
};

/** How a date reads in the field: the month spelled, so 03/04 is never a question. */
function shown(iso: string): string {
  return isIsoDate(iso) ? formatIso(iso, { day: "numeric", month: "short", year: "numeric" }) : "";
}

/**
 * THE date control (RADD-1563, RADD-1566): a text field that shows the date
 * with its month spelled, and the app's own calendar under it — the native
 * date input reads 09/22/2026 on one machine and 22/09/2026 on the next, and
 * its popup is a different widget in each browser.
 *
 * It keeps the native input's contract so nothing that used it changed:
 * `value` is an ISO date, and `onChange` receives an event whose
 * `target.value` is an ISO date or "". Typing accepts ISO, the locale's
 * numeric order and a spelled month; what cannot be read is kept on screen
 * and marked, never silently dropped. `className` is for layout only.
 */
export function DateInput({
  value,
  onChange,
  min,
  max,
  disabled,
  invalid,
  className = "",
  placeholder,
  onBlur,
  onKeyDown,
  "aria-label": ariaLabel,
  ...props
}: DateInputProps) {
  const iso = typeof value === "string" && isIsoDate(value) ? value : "";
  const wrap = useRef<HTMLSpanElement>(null);
  const input = useRef<HTMLInputElement>(null);
  /** Text being typed; null = show the value. */
  const [draft, setDraft] = useState<string | null>(null);
  const [unread, setUnread] = useState(false);
  const [open, setOpen] = useState<null | "pointer" | "keys">(null);
  const order = useMemo(() => localeDateOrder(), []);
  const months = useMemo(() => localeMonthNames(), []);
  const hint = order === "mdy" ? "Nov 22, 2026 or 11/22/2026" : order === "ymd" ? "2026-11-22" : "22 Nov 2026 or 22/11/2026";

  const emit = (next: string) => {
    if (next === iso) return;
    onChange?.({ target: { value: next }, currentTarget: { value: next } } as ChangeEvent<HTMLInputElement>);
  };
  /** Take what was typed. False when it could not be read or is out of range. */
  const commit = (): boolean => {
    if (draft === null) return true;
    const text = draft.trim();
    const parsed = text ? parseTypedDate(text, order, months) : "";
    if (parsed === null || (parsed && !inRange(parsed, min, max))) {
      setUnread(true);
      return false;
    }
    setDraft(null);
    setUnread(false);
    emit(parsed);
    return true;
  };
  const close = useCallback((refocus: boolean) => {
    setOpen(null);
    if (refocus) input.current?.focus();
  }, []);

  const problem = unread
    ? draft && parseTypedDate(draft.trim(), order, months)
      ? `Outside the allowed dates${min ? `, from ${shown(min)}` : ""}${max ? `, to ${shown(max)}` : ""}`
      : `Not a date. Try ${hint}`
    : undefined;

  return (
    <span
      ref={wrap}
      data-date-input
      className={
        fieldClasses +
        (unread || invalid ? "border-status-danger " : "border-strong ") +
        (disabled ? "cursor-not-allowed opacity-70 " : "") +
        // A default width only when the caller gave none: two width utilities on one
        // element are settled by stylesheet order, not by which was written last.
        (/(^|\s)w-/.test(className) ? "" : "w-40 ") +
        className
      }
    >
      <input
        {...props}
        ref={input}
        type="text"
        inputMode="text"
        autoComplete="off"
        disabled={disabled}
        aria-label={ariaLabel}
        aria-invalid={unread || invalid || undefined}
        aria-haspopup="dialog"
        aria-expanded={open !== null}
        title={problem}
        placeholder={placeholder ?? "No date"}
        value={draft ?? shown(iso)}
        onChange={(event) => {
          const text = event.target.value;
          setDraft(text);
          setUnread(false);
          // A complete ISO date is unambiguous the moment it is whole, so it is
          // taken at once (as the native input did, and as a script filling the
          // field expects). Every other form waits for Enter or blur: "1/2/20"
          // on the way to "1/2/2026" is a date too, and must not be saved.
          if (isIsoDate(text.trim()) && inRange(text.trim(), min, max)) emit(text.trim());
        }}
        onClick={() => !disabled && setOpen((was) => was ?? "pointer")}
        onBlur={(event) => {
          // Focus going into the calendar is not leaving the field.
          const to = event.relatedTarget as HTMLElement | null;
          if (!to?.closest("[data-date-calendar]")) commit();
          onBlur?.(event);
        }}
        onKeyDown={(event) => {
          onKeyDown?.(event);
          if (event.defaultPrevented) return;
          if (event.key === "Enter") {
            if (draft !== null) {
              // The typed date is the answer; do not also submit a form with the old one.
              event.preventDefault();
              if (commit()) setOpen(null);
            }
          } else if (event.key === "ArrowDown") {
            event.preventDefault();
            if (commit()) setOpen("keys");
          } else if (event.key === "Escape" && (open || draft !== null)) {
            event.preventDefault();
            event.stopPropagation();
            setOpen(null);
            setDraft(null);
            setUnread(false);
          }
        }}
        className="h-full min-w-0 flex-1 rounded-md bg-transparent px-2 outline-none placeholder:text-fg-faint disabled:cursor-not-allowed"
      />
      <button
        type="button"
        tabIndex={-1}
        disabled={disabled}
        aria-label="Open the calendar"
        onClick={() => setOpen((was) => (was ? null : "pointer"))}
        className="mr-1 flex size-6 shrink-0 items-center justify-center rounded text-fg-muted hover:bg-elevated hover:text-heading cursor-pointer disabled:cursor-not-allowed"
      >
        <CalendarDays size={14} aria-hidden />
      </button>
      {open && wrap.current && (
        <CalendarPopover
          anchor={wrap.current}
          value={iso}
          min={min}
          max={max}
          label={ariaLabel ?? "Date"}
          focusGrid={open === "keys"}
          onPick={(next) => {
            setDraft(null);
            setUnread(false);
            emit(next);
          }}
          onClose={close}
        />
      )}
    </span>
  );
}

export function DateField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-xs font-medium text-fg-secondary">
        {label}
      </label>
      <DateInput id={id} aria-label={label} value={value ?? ""} onChange={(event) => onChange(event.target.value || null)} />
    </div>
  );
}
