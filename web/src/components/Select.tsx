import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Check, ChevronDown } from "lucide-react";

export interface SelectOption {
  value: string;
  label: ReactNode;
  disabled?: boolean;
  /** Tooltip on the option row (e.g. why it's disabled). */
  title?: string;
}

interface SelectProps {
  value: string;
  onChange: (value: string) => void;
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

/** Plain text of an option label, for type-ahead matching. */
function labelText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(labelText).join("");
  if (typeof node === "object" && "props" in node) {
    return labelText((node.props as { children?: ReactNode }).children);
  }
  return "";
}

/**
 * Styled single-select listbox (the native `<select>` replacement): a
 * TextField-styled button + an anchored option panel. Keyboard: ↑/↓/Home/End
 * move, Enter/Space commit, Escape closes (focus returns to the trigger),
 * printable characters type-ahead (space included once a search is going).
 * Closes on outside pointer down or resize — never on scroll, since the panel
 * is anchored to the trigger and travels with it.
 */
export function Select({
  value,
  onChange,
  options,
  placeholder,
  disabled = false,
  invalid = false,
  size = "md",
  className = "",
  triggerClassName = "",
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
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const typeahead = useRef({ term: "", at: 0 });

  const selectedIndex = options.findIndex((option) => option.value === value);
  const selected = selectedIndex >= 0 ? options[selectedIndex] : undefined;

  const close = (focusTrigger = false) => {
    setOpen(false);
    if (focusTrigger) triggerRef.current?.focus();
  };

  const openList = (index?: number) => {
    if (disabled) return;
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) {
      const needed = Math.min(options.length * ROW_HEIGHT + 8, PANEL_MAX_HEIGHT);
      const below = window.innerHeight - rect.bottom;
      setDropUp(needed > below && rect.top > below);
      // Keep the panel on-screen horizontally: right-edge triggers anchor right.
      const panelWidth = Math.max(rect.width, PANEL_MIN_WIDTH);
      setAlignEnd(rect.left + panelWidth > window.innerWidth - 8 && rect.right >= panelWidth);
    }
    setHighlight(index ?? (selectedIndex >= 0 ? selectedIndex : firstEnabled()));
    setOpen(true);
  };

  const firstEnabled = () => options.findIndex((option) => !option.disabled);

  const commit = (index: number) => {
    const option = options[index];
    if (!option || option.disabled) return;
    if (option.value !== value) onChange(option.value);
    close(true);
  };

  /** Move the highlight `delta` rows, skipping disabled options; wraps. */
  const move = (delta: number) => {
    if (options.length === 0) return;
    let next = highlight;
    for (let step = 0; step < options.length; step += 1) {
      next = (next + delta + options.length) % options.length;
      if (!options[next].disabled) break;
    }
    setHighlight(next);
  };

  const jumpTo = (index: number) => {
    if (options[index] && !options[index].disabled) setHighlight(index);
  };

  /** Prefix match from the current highlight, cycling; mirrors native selects. */
  const typeAhead = (char: string) => {
    const now = Date.now();
    const buffer = typeahead.current;
    buffer.term = now - buffer.at < 600 ? buffer.term + char : char;
    buffer.at = now;
    const term = buffer.term.toLowerCase();
    const match = options.findIndex(
      (option, index) =>
        !option.disabled &&
        index > (open ? highlight : selectedIndex) &&
        labelText(option.label).trim().toLowerCase().startsWith(term),
    );
    const wrapped =
      match >= 0
        ? match
        : options.findIndex(
            (option) =>
              !option.disabled && labelText(option.label).trim().toLowerCase().startsWith(term),
          );
    if (wrapped < 0) return;
    if (open) setHighlight(wrapped);
    else openList(wrapped);
  };

  // Focus the listbox on open; keep the highlighted row in view.
  useLayoutEffect(() => {
    if (!open) return;
    listRef.current?.focus();
    listRef.current
      ?.querySelector(`[data-index="${highlight}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [open, highlight]);

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
          jumpTo(options.length - 1 - [...options].reverse().findIndex((o) => !o.disabled));
        }
        break;
      case "Tab":
        close();
        break;
      default:
        if (event.key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey) {
          event.preventDefault();
          typeAhead(event.key);
        }
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
            ? " border-red-500/60 focus:border-red-400 focus:ring-red-400/30 "
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
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          tabIndex={-1}
          aria-label={ariaLabel}
          aria-labelledby={ariaLabelledBy}
          aria-activedescendant={activeId}
          onKeyDown={onTriggerKeyDown}
          className={
            "absolute z-40 max-h-60 w-full min-w-48 overflow-y-auto rounded-lg border " +
            "border-subtle bg-surface p-1 shadow-pop animate-menu-in focus:outline-none " +
            (alignEnd ? "right-0 " : "left-0 ") +
            (dropUp ? "bottom-full mb-1" : "top-full mt-1")
          }
        >
          {options.map((option, index) => {
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
          {options.length === 0 && (
            <li className="px-2 py-1.5 text-[13px] text-fg-faint">No options</li>
          )}
        </ul>
      )}
    </div>
  );
}
