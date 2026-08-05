import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { Check, X } from "lucide-react";

export interface TokenOption {
  /** The stored value (an id, key, or the literal label for free-text sets). */
  value: string;
  /** Display text in the chip and the dropdown row. */
  label: string;
  /** Secondary dropdown text (a project name, an email) — also matched by the filter. */
  hint?: string;
  /** Optional group header the option sorts under in the dropdown. */
  group?: string;
  /** Optional leading icon (e.g. a team glyph) shown in the chip and the dropdown row. */
  icon?: ReactNode;
}

interface TokenMultiSelectProps {
  value: string[];
  onChange: (next: string[]) => void;
  options: TokenOption[];
  placeholder?: string;
  /** Allow committing a free-text token that isn't in `options` (labels, field options). */
  allowCreate?: boolean;
  /** Text for the "create" dropdown row (default: Create "term"). */
  createLabel?: (term: string) => string;
  disabled?: boolean;
  invalid?: boolean;
  autoFocus?: boolean;
  ariaLabel?: string;
  id?: string;
}

/** Dropdown render cap (RADD-881) — matches Select's filtering behavior: the
 * highlight/keyboard space is the VISIBLE rows, a tail row names the rest. */
const MAX_VISIBLE_MATCHES = 50;

/**
 * One compact multi-select used across the app (replacing the tall wrapping-pill editors): selected
 * values are chips on a SINGLE row that scrolls sideways, with a typeahead input at the end and an
 * autocomplete dropdown. Pick from `options` (optionally grouped), or free-text create when
 * `allowCreate`. Keyboard: type to filter, ↑/↓ to move, Enter/comma to add, Backspace to remove the
 * last chip, Esc to close; each chip has an × to remove. Values not present in `options` show their
 * own text as the chip label (so free-text sets round-trip).
 */
export function TokenMultiSelect({
  value,
  onChange,
  options,
  placeholder,
  allowCreate = false,
  createLabel = (t) => `Create “${t}”`,
  disabled = false,
  invalid = false,
  autoFocus = false,
  ariaLabel,
  id,
}: TokenMultiSelectProps) {
  const genId = useId();
  const inputId = id ?? genId;
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [highlight, setHighlight] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const byValue = useMemo(() => new Map(options.map((o) => [o.value, o])), [options]);
  const chipLabel = (v: string) => byValue.get(v)?.label ?? v;
  const chipIcon = (v: string) => byValue.get(v)?.icon;

  const t = term.trim().toLowerCase();
  const selected = useMemo(() => new Set(value), [value]);
  const filtered = useMemo(() => {
    const avail = options.filter((o) => !selected.has(o.value));
    const matches = t
      ? avail.filter((o) => `${o.label} ${o.hint ?? ""}`.toLowerCase().includes(t))
      : avail;
    // Stable group ordering: options with a group first (in first-seen group order), then ungrouped.
    const groupOrder: string[] = [];
    for (const o of matches) if (o.group && !groupOrder.includes(o.group)) groupOrder.push(o.group);
    return [...matches].sort(
      (a, b) => (a.group ? groupOrder.indexOf(a.group) : groupOrder.length) -
        (b.group ? groupOrder.indexOf(b.group) : groupOrder.length),
    );
  }, [options, selected, t]);

  // Render cap (RADD-881): 2,016 label options used to mount 2k DOM rows on
  // every keystroke. Past the cap a tail row reports what's hiding.
  const visible = filtered.length > MAX_VISIBLE_MATCHES
    ? filtered.slice(0, MAX_VISIBLE_MATCHES)
    : filtered;
  const hiddenCount = filtered.length - visible.length;

  const termExists =
    t !== "" &&
    (options.some((o) => o.label.toLowerCase() === t) || value.some((v) => v.toLowerCase() === t));
  const showCreate = allowCreate && t !== "" && !termExists;
  const navCount = visible.length + (showCreate ? 1 : 0);

  useEffect(() => setHighlight(0), [term, open]);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const addValue = (v: string) => {
    if (!value.includes(v)) onChange([...value, v]);
    setTerm("");
    setOpen(true);
    inputRef.current?.focus();
  };
  const createValue = (raw: string) => {
    const name = raw.trim().replace(/,+$/, "");
    setTerm("");
    if (name && !value.includes(name)) onChange([...value, name]);
  };
  const removeValue = (v: string) => onChange(value.filter((x) => x !== v));

  const commitHighlight = () => {
    if (showCreate && highlight === visible.length) createValue(term);
    else if (visible[highlight]) addValue(visible[highlight].value);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commitHighlight();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setHighlight((h) => (navCount ? (h + 1) % navCount : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => (navCount ? (h - 1 + navCount) % navCount : 0));
    } else if (e.key === "Backspace" && term === "" && value.length > 0) {
      removeValue(value[value.length - 1]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  let flatIndex = -1; // running index across grouped rows, to align with `highlight`
  let lastGroup: string | undefined;

  return (
    <div ref={rootRef} className="relative">
      <div
        onMouseDown={(e) => {
          if (e.target === e.currentTarget && !disabled) inputRef.current?.focus();
        }}
        className={
          "flex h-8 items-center gap-1 overflow-x-auto rounded-md border bg-surface px-1.5 " +
          "[scrollbar-width:none] [&::-webkit-scrollbar]:hidden " +
          "focus-within:outline-none focus-within:ring-2 " +
          (disabled ? "opacity-60 " : "") +
          (invalid
            ? "border-status-danger/60 focus-within:border-status-danger focus-within:ring-status-danger/30"
            : "border-subtle focus-within:border-accent focus-within:ring-accent/30")
        }
      >
        {value.map((v) => (
          <span
            key={v}
            className="inline-flex shrink-0 items-center gap-1 rounded border border-subtle bg-elevated py-px pl-1.5 pr-0.5 text-[11px] leading-4 text-fg"
          >
            {chipIcon(v)}
            <span className="max-w-40 truncate">{chipLabel(v)}</span>
            {!disabled && (
              <button
                type="button"
                aria-label={`Remove ${chipLabel(v)}`}
                onClick={() => removeValue(v)}
                className="shrink-0 rounded text-fg-muted hover:text-red-400 cursor-pointer"
              >
                <X size={11} aria-hidden />
              </button>
            )}
          </span>
        ))}
        <input
          id={inputId}
          ref={inputRef}
          value={term}
          disabled={disabled}
          autoFocus={autoFocus}
          aria-label={ariaLabel}
          aria-invalid={invalid || undefined}
          role="combobox"
          aria-expanded={open}
          aria-controls={`${inputId}-list`}
          autoComplete="off"
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            const raw = e.target.value;
            if (allowCreate && raw.endsWith(",")) createValue(raw.slice(0, -1));
            else setTerm(raw);
            setOpen(true);
          }}
          onKeyDown={onKeyDown}
          placeholder={value.length === 0 ? placeholder : ""}
          className="h-full min-w-16 flex-1 bg-transparent text-[13px] text-heading placeholder:text-fg-faint outline-none"
        />
      </div>

      {open && !disabled && (filtered.length > 0 || showCreate) && (
        <ul
          id={`${inputId}-list`}
          role="listbox"
          className="absolute left-0 top-full z-30 mt-1 max-h-56 w-full min-w-56 overflow-y-auto rounded-md border border-subtle bg-surface p-1 shadow-pop"
        >
          {visible.map((o) => {
            flatIndex += 1;
            const idx = flatIndex;
            const groupHeader = o.group && o.group !== lastGroup ? o.group : null;
            lastGroup = o.group;
            return (
              <li key={o.value}>
                {groupHeader && (
                  <div className="px-2 pb-0.5 pt-1.5 text-[10px] uppercase tracking-wide text-fg-faint">
                    {groupHeader}
                  </div>
                )}
                <button
                  type="button"
                  role="option"
                  aria-selected={idx === highlight}
                  onMouseEnter={() => setHighlight(idx)}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    addValue(o.value);
                  }}
                  className={
                    "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs cursor-pointer " +
                    (idx === highlight ? "bg-overlay text-heading" : "text-fg hover:bg-overlay/60")
                  }
                >
                  {o.icon}
                  <span className="truncate">{o.label}</span>
                  {o.hint && <span className="truncate text-fg-muted">{o.hint}</span>}
                  <Check size={12} className="ml-auto shrink-0 text-accent-text opacity-0" aria-hidden />
                </button>
              </li>
            );
          })}
          {hiddenCount > 0 && (
            <li className="px-2 py-1.5 text-[11px] text-fg-faint" aria-live="polite">
              Keep typing — {hiddenCount.toLocaleString()} more match{hiddenCount === 1 ? "" : "es"}
            </li>
          )}
          {showCreate && (
            <li>
              <button
                type="button"
                role="option"
                aria-selected={highlight === visible.length}
                onMouseEnter={() => setHighlight(visible.length)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  createValue(term);
                }}
                className={
                  "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs cursor-pointer " +
                  (highlight === visible.length
                    ? "bg-overlay text-heading"
                    : "text-fg hover:bg-overlay/60")
                }
              >
                <span className="truncate">{createLabel(term.trim())}</span>
              </button>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
