import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Check, ChevronDown, Search } from "lucide-react";

export interface SelectOption {
  value: string;
  label: ReactNode;
  disabled?: boolean;
  /** Tooltip on the option row (e.g. why it's disabled). */
  title?: string;
  /** Searchable text when `label` is a COMPONENT (e.g. <PersonName/>) — the
   * kit can only extract text from literal children, so component labels
   * declare theirs (RADD-881; `<option label="…">` feeds this via SelectField). */
  text?: string;
}

interface SelectProps {
  value: string;
  onChange: (value: string) => void;
  /** Prepare choices on pointer or keyboard opening. */
  onOpen?: () => void;
  options: SelectOption[];
  /** Trigger text when no option matches `value`. */
  placeholder?: string;
  disabled?: boolean;
  /** Red error ring (SelectField's `error`). */
  invalid?: boolean;
  /** sm = h-7 text-xs (inline rows); md = h-8 px-2.5 text-[13px] (matches TextField). */
  size?: "sm" | "md";
  /** Extra classes on the relative wrapper (width, margins). */
  className?: string;
  /** Extra classes on the trigger button (rare — layout belongs on `className`). */
  triggerClassName?: string;
  /** Filter input in the panel. Defaults ON above SEARCHABLE_THRESHOLD options
   * (RADD-881) so every call site inherits it — pass false to force it off. */
  searchable?: boolean;
  id?: string;
  title?: string;
  "aria-label"?: string;
  "aria-labelledby"?: string;
  "aria-describedby"?: string;
}

const sizeClasses = {
  sm: "h-7 pl-2 pr-6 text-xs",
  md: "h-8 pl-2.5 pr-7 text-[13px]",
} as const;

const PANEL_MAX_HEIGHT = 240; // max-h-60
const PANEL_MIN_WIDTH = 192; // min-w-48
const ROW_HEIGHT = 32;
/** Above this many options the panel grows a filter input (RADD-881): the kit's
 * jump type-ahead was the only "search" a 1,031-option user picker had. */
const SEARCHABLE_THRESHOLD = 15;
/** Cap on rendered rows while filtering — 2,016 labels once mounted 2k DOM
 * nodes; past the cap a tail row says how many more are hiding. */
const MAX_RENDERED_OPTIONS = 200;

/** Plain text of an option label, for type-ahead + filter matching. */
function labelText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(labelText).join("");
  if (typeof node === "object" && "props" in node) {
    return labelText((node.props as { children?: ReactNode }).children);
  }
  return "";
}

/** The text an option is searched by: declared `text` first, extracted second. */
function optionText(option: SelectOption): string {
  return option.text ?? labelText(option.label);
}

/**
 * Styled single-select listbox (the native `<select>` replacement): a
 * TextField-styled button + an anchored option panel. Keyboard: ↑/↓/Home/End
 * move, Enter/Space commit, Escape closes (focus returns to the trigger),
 * printable characters type-ahead (space included once a search is going).
 * Above SEARCHABLE_THRESHOLD options the panel carries a filter input instead:
 * typing filters the rows (capped at MAX_RENDERED_OPTIONS), ↑/↓/Enter work from
 * the input, and a printable key on the closed trigger opens pre-filtered.
 * Closes on outside pointer down or resize — never on scroll, since the panel
 * is anchored to the trigger and travels with it.
 */
export function Select({
  value,
  onChange,
  onOpen,
  options,
  placeholder,
  disabled = false,
  invalid = false,
  size = "md",
  className = "",
  triggerClassName = "",
  searchable: searchableProp,
  id,
  title,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
  "aria-describedby": ariaDescribedBy,
}: SelectProps) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(-1);
  const [dropUp, setDropUp] = useState(false);
  const [alignEnd, setAlignEnd] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const typeahead = useRef({ term: "", at: 0 });

  const searchable = searchableProp ?? options.length > SEARCHABLE_THRESHOLD;

  const selected = options.find((option) => option.value === value);

  // The panel renders VISIBLE rows: filtered (searchable, query set) and capped.
  // Each row keeps its original option; highlight/commit index into `visible`.
  const normalizedQuery = searchable ? query.trim().toLowerCase() : "";
  const filtered = useMemo(() => {
    if (!normalizedQuery) return options;
    return options.filter((option) => {
      const text = optionText(option);
      // Fail OPEN on unreadable labels: an option whose text the kit cannot
      // see must never be silently hidden by a filter it can't match.
      return text === "" || text.toLowerCase().includes(normalizedQuery);
    });
  }, [options, normalizedQuery]);
  const visible = filtered.length > MAX_RENDERED_OPTIONS
    ? filtered.slice(0, MAX_RENDERED_OPTIONS)
    : filtered;
  const hiddenCount = filtered.length - visible.length;

  const selectedVisibleIndex = visible.findIndex((option) => option.value === value);

  const close = (focusTrigger = false) => {
    setOpen(false);
    setQuery("");
    if (focusTrigger) triggerRef.current?.focus();
  };

  const openList = (index?: number, seedQuery = "") => {
    if (disabled) return;
    onOpen?.();
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) {
      const rows = Math.min(options.length * ROW_HEIGHT + 8, PANEL_MAX_HEIGHT);
      const needed = searchable ? rows + ROW_HEIGHT : rows;
      const below = window.innerHeight - rect.bottom;
      setDropUp(needed > below && rect.top > below);
      // Keep the panel on-screen horizontally: right-edge triggers anchor right.
      const panelWidth = Math.max(rect.width, PANEL_MIN_WIDTH);
      setAlignEnd(rect.left + panelWidth > window.innerWidth - 8 && rect.right >= panelWidth);
    }
    setQuery(seedQuery);
    setHighlight(index ?? (selectedVisibleIndex >= 0 ? selectedVisibleIndex : firstEnabled()));
    setOpen(true);
  };

  const firstEnabled = () => visible.findIndex((option) => !option.disabled);

  const commit = (index: number) => {
    const option = visible[index];
    if (!option || option.disabled) return;
    if (option.value !== value) onChange(option.value);
    close(true);
  };

  /** Move the highlight `delta` rows, skipping disabled options; wraps. */
  const move = (delta: number) => {
    if (visible.length === 0) return;
    let next = highlight;
    for (let step = 0; step < visible.length; step += 1) {
      next = (next + delta + visible.length) % visible.length;
      if (!visible[next].disabled) break;
    }
    setHighlight(next);
  };

  const jumpTo = (index: number) => {
    if (visible[index] && !visible[index].disabled) setHighlight(index);
  };

  /** Prefix match from the current highlight, cycling; mirrors native selects.
   * Only the non-searchable path — a searchable panel filters instead. */
  const typeAhead = (char: string) => {
    const now = Date.now();
    const buffer = typeahead.current;
    buffer.term = now - buffer.at < 600 ? buffer.term + char : char;
    buffer.at = now;
    const term = buffer.term.toLowerCase();
    const from = open ? highlight : selectedVisibleIndex;
    const match = visible.findIndex(
      (option, index) =>
        !option.disabled &&
        index > from &&
        optionText(option).trim().toLowerCase().startsWith(term),
    );
    const wrapped =
      match >= 0
        ? match
        : visible.findIndex(
            (option) =>
              !option.disabled && optionText(option).trim().toLowerCase().startsWith(term),
          );
    if (wrapped < 0) return;
    if (open) setHighlight(wrapped);
    else openList(wrapped);
  };

  // Focus the panel on open (the filter input when searchable, else the list);
  // keep the highlighted row in view.
  useLayoutEffect(() => {
    if (!open) return;
    if (searchable) searchRef.current?.focus();
    else listRef.current?.focus();
    listRef.current
      ?.querySelector(`[data-index="${highlight}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [open, highlight, searchable]);

  // A new filter invalidates the old highlight — land on the first hit.
  useEffect(() => {
    if (!open || !searchable) return;
    setHighlight(visible.findIndex((option) => !option.disabled));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset on query change only
  }, [normalizedQuery]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) close();
    };
    // No close-on-scroll: the panel is anchored to the trigger inside the same
    // relative wrapper, so it travels with it on page scroll — and a capture
    // listener would also fire on the panel's OWN scrolling (long option lists
    // vanished on open, and wheel/type-ahead closed the panel).
    const onPassiveClose = () => close();
    document.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("resize", onPassiveClose);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("resize", onPassiveClose);
    };
  }, [open]);

  const onTriggerKeyDown = (event: React.KeyboardEvent) => {
    if (disabled) return;
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        if (!open) openList();
        else move(1);
        break;
      case "ArrowUp":
        event.preventDefault();
        if (!open) openList();
        else move(-1);
        break;
      case "Enter":
        event.preventDefault();
        if (open) commit(highlight);
        else openList();
        break;
      case " ":
        event.preventDefault();
        if (!open) {
          openList();
        } else if (typeahead.current.term && Date.now() - typeahead.current.at < 600) {
          // Mid-type-ahead, space is a search character (labels contain spaces),
          // not "commit the highlighted option".
          typeAhead(" ");
        } else {
          commit(highlight);
        }
        break;
      case "Escape":
        if (open) {
          event.preventDefault();
          // Keep the key from reaching a surrounding Modal's Escape handler.
          event.stopPropagation();
          close(true);
        }
        break;
      case "Home":
        if (open) {
          event.preventDefault();
          jumpTo(firstEnabled());
        }
        break;
      case "End":
        if (open) {
          event.preventDefault();
          jumpTo(visible.length - 1 - [...visible].reverse().findIndex((o) => !o.disabled));
        }
        break;
      case "Tab":
        close();
        break;
      default:
        if (event.key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey) {
          event.preventDefault();
          if (searchable) {
            // A printable key on the closed trigger opens pre-filtered; when
            // open, focus is already in the input and never reaches here.
            if (!open) openList(undefined, event.key);
            else setQuery((current) => current + event.key);
          } else {
            typeAhead(event.key);
          }
        }
    }
  };

  /** The filter input owns navigation keys while its text edits stay native. */
  const onSearchKeyDown = (event: React.KeyboardEvent) => {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        move(1);
        break;
      case "ArrowUp":
        event.preventDefault();
        move(-1);
        break;
      case "Enter":
        event.preventDefault();
        commit(highlight);
        break;
      case "Escape":
        event.preventDefault();
        event.stopPropagation();
        close(true);
        break;
      case "Tab":
        close();
        break;
    }
  };

  const activeId = open && highlight >= 0 ? `${listId}-${highlight}` : undefined;

  return (
    <div ref={rootRef} className={`relative ${className}`}>
      <button
        ref={triggerRef}
        type="button"
        id={id}
        title={title}
        disabled={disabled}
        onClick={() => (open ? close(true) : openList())}
        onKeyDown={onTriggerKeyDown}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        aria-describedby={ariaDescribedBy}
        aria-invalid={invalid || undefined}
        className={
          "flex w-full items-center justify-between gap-2 rounded-md border bg-surface text-left " +
          "focus:outline-none focus:ring-2 cursor-pointer " +
          "disabled:cursor-not-allowed disabled:opacity-70 " +
          sizeClasses[size] +
          (invalid
            ? " border-status-danger/60 focus:border-status-danger focus:ring-status-danger/30 "
            : " border-subtle focus:border-accent focus:ring-accent/30 ") +
          triggerClassName
        }
      >
        <span className={`min-w-0 flex-1 truncate ${selected ? "text-heading" : "text-fg-faint"}`}>
          {selected ? selected.label : (placeholder ?? "")}
        </span>
        <ChevronDown
          size={size === "sm" ? 12 : 14}
          className={`shrink-0 text-fg-muted transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>

      {open && (
        <div
          className={
            "absolute z-40 w-full min-w-48 rounded-lg border border-subtle bg-surface " +
            "shadow-pop animate-menu-in " +
            (alignEnd ? "right-0 " : "left-0 ") +
            (dropUp ? "bottom-full mb-1" : "top-full mt-1")
          }
        >
          {searchable && (
            <div className="flex items-center gap-1.5 border-b border-subtle px-2 py-1.5">
              <Search size={12} className="shrink-0 text-fg-faint" aria-hidden />
              <input
                ref={searchRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={onSearchKeyDown}
                placeholder="Filter…"
                role="combobox"
                aria-expanded
                aria-controls={listId}
                aria-activedescendant={activeId}
                aria-label={ariaLabel ? `Filter ${ariaLabel}` : "Filter options"}
                className="w-full bg-transparent text-[13px] text-fg placeholder:text-fg-faint focus:outline-none"
              />
            </div>
          )}
          <ul
            ref={listRef}
            id={listId}
            role="listbox"
            tabIndex={-1}
            aria-label={ariaLabel}
            aria-labelledby={ariaLabelledBy}
            aria-activedescendant={activeId}
            onKeyDown={onTriggerKeyDown}
            className="max-h-60 overflow-y-auto p-1 focus:outline-none"
          >
            {visible.map((option, index) => {
              const isSelected = option.value === value;
              const isHighlighted = index === highlight;
              return (
                <li
                  key={index}
                  id={`${listId}-${index}`}
                  data-index={index}
                  role="option"
                  aria-selected={isSelected}
                  aria-disabled={option.disabled || undefined}
                  title={option.title}
                  onMouseEnter={() => !option.disabled && setHighlight(index)}
                  // pointerdown (not click) so the pick lands before the panel closes.
                  onPointerDown={(event) => {
                    event.preventDefault();
                    commit(index);
                  }}
                  className={
                    "flex items-center gap-2 rounded px-2 py-1.5 text-[13px] " +
                    (option.disabled
                      ? "cursor-not-allowed text-fg-faint"
                      : "cursor-pointer " +
                        (isHighlighted
                          ? "bg-overlay text-heading"
                          : isSelected
                            ? "text-heading"
                            : "text-fg"))
                  }
                >
                  <span className="min-w-0 flex-1 truncate">{option.label}</span>
                  {isSelected && (
                    <Check size={13} className="shrink-0 text-accent" aria-hidden />
                  )}
                </li>
              );
            })}
            {hiddenCount > 0 && (
              <li className="px-2 py-1.5 text-xs text-fg-faint" aria-live="polite">
                Keep typing — {hiddenCount.toLocaleString()} more match{hiddenCount === 1 ? "" : "es"}
              </li>
            )}
            {visible.length === 0 && (
              <li className="px-2 py-1.5 text-[13px] text-fg-faint">
                {normalizedQuery ? "No matches" : "No options"}
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
