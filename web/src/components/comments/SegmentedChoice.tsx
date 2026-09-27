import type { HTMLAttributes, KeyboardEvent } from "react";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  /** The chosen option's colours, when it should read differently (an internal note is amber). */
  activeClassName?: string;
}

/** Where an arrow or Home/End key moves the selection in a radio group; other keys do nothing. */
function nextIndex(key: string, current: number, count: number): number | null {
  switch (key) {
    case "ArrowRight":
    case "ArrowDown":
      return (current + 1) % count;
    case "ArrowLeft":
    case "ArrowUp":
      return (current - 1 + count) % count;
    case "Home":
      return 0;
    case "End":
      return count - 1;
    default:
      return null;
  }
}

/**
 * A small either/or switch drawn as one bordered pill of radio buttons: the composer's
 * Comment | Thread mode and its Public reply | Internal note audience. Each option carries
 * `data-option` for proofs; any other attribute lands on the group.
 *
 * Keyboard (RADD-1463): a radio group is ONE tab stop — only the checked option is tabbable,
 * and the arrow keys (plus Home/End) move the selection, as native radios do. Before, every
 * option was its own stop and the arrows did nothing.
 */
export function SegmentedChoice<T extends string>({
  label,
  value,
  options,
  onChange,
  className = "",
  onKeyDown,
  ...group
}: {
  label: string;
  value: T;
  options: readonly SegmentedOption<T>[];
  onChange: (value: T) => void;
} & Omit<HTMLAttributes<HTMLDivElement>, "onChange">) {
  const checkedIndex = Math.max(0, options.findIndex((option) => option.value === value));
  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown?.(event);
    if (event.defaultPrevented) return;
    const target = nextIndex(event.key, checkedIndex, options.length);
    if (target === null || options.length === 0) return;
    event.preventDefault();
    const option = options[target];
    onChange(option.value);
    event.currentTarget.querySelector<HTMLButtonElement>(`[data-option="${option.value}"]`)?.focus();
  };
  return (
    <div
      role="radiogroup"
      aria-label={label}
      {...group}
      onKeyDown={move}
      className={"flex gap-1 self-start rounded-md border border-subtle p-0.5 " + className}
    >
      {options.map((option, index) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={index === checkedIndex ? 0 : -1}
            data-option={option.value}
            onClick={() => onChange(option.value)}
            className={
              "rounded px-2 py-0.5 text-[11px] font-medium cursor-pointer transition-colors " +
              "focus-visible:outline-2 focus-visible:outline-focus " +
              (active ? option.activeClassName ?? "bg-elevated text-heading" : "text-fg-muted hover:text-fg")
            }
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
