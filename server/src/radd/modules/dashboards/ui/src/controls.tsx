/** The pickers and toggles the widget form draws with — the owners' slots, and one small toggle. */
import type { ReactNode } from "react";
import { Button, Slot } from "@radd/plugin-sdk";
import { PROJECT_SELECT_SLOT, type ProjectSelectProps } from "@radd-plugin-ui/projects/picker-contract";
import { CYCLE_SELECT_SLOT, type CycleSelectProps } from "@radd-plugin-ui/cycles/picker-contract";

/** The Projects plugin's select; Projects owns its rendering and queries. */
export function ProjectSelect(props: ProjectSelectProps) {
  const fallback = <Button disabled variant="secondary" aria-label={props.label}>Selection unavailable{props.value ? ` · ${props.value}` : ""}</Button>;
  return <Slot id={PROJECT_SELECT_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}

/** The Cycles plugin's select. */
export function CycleSelect(props: CycleSelectProps) {
  const fallback = <Button disabled variant="secondary" aria-label={props.label ?? props.placeholder}>Selection unavailable{props.value ? ` · ${props.value}` : ""}</Button>;
  return <Slot id={CYCLE_SELECT_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}

/** A compact one-of-few toggle (bucket interval, Count ↔ Points), as the report cards draw it. */
export function Segmented<T extends string>({ ariaLabel, value, options, onChange }: {
  ariaLabel: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={ariaLabel} className="flex w-fit rounded-md border border-subtle p-0.5">
      {options.map((option) => (
        <button key={option.value} type="button" onClick={() => onChange(option.value)} aria-pressed={value === option.value}
          className={"cursor-pointer rounded px-2 py-0.5 text-xs focus-visible:outline-2 focus-visible:outline-focus " +
            (value === option.value ? "bg-elevated text-heading" : "text-fg-muted hover:text-fg")}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** A labelled row for a control that is not a form field. */
export function LabeledControl({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-fg-secondary">{label}</span>
      <div>{children}</div>
    </div>
  );
}
