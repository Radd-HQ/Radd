import type { HTMLAttributes } from "react";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  /** The chosen option's colours, when it should read differently (an internal note is amber). */
  activeClassName?: string;
}

/**
 * A small either/or switch drawn as one bordered pill of radio buttons: the composer's
 * Comment | Thread mode and its Public reply | Internal note audience. Each option carries
 * `data-option` for proofs; any other attribute lands on the group.
 */
export function SegmentedChoice<T extends string>({
  label,
  value,
  options,
  onChange,
  className = "",
  ...group
}: {
  label: string;
  value: T;
  options: readonly SegmentedOption<T>[];
  onChange: (value: T) => void;
} & Omit<HTMLAttributes<HTMLDivElement>, "onChange">) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      {...group}
      className={"flex gap-1 self-start rounded-md border border-subtle p-0.5 " + className}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
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
