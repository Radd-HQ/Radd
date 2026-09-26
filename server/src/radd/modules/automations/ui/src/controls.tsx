import type { ReactNode } from "react";
import { Slot, Button } from "@radd/plugin-sdk";
import { PROJECT_SELECT_SLOT, type ProjectSelectProps } from "@radd-plugin-ui/projects/picker-contract";
import { CYCLE_SELECT_SLOT, type CycleSelectProps } from "@radd-plugin-ui/cycles/picker-contract";
import { FIELD_CONTROL_SLOT, type ControlProps } from "@radd-plugin-ui/fields/control-contract";
export function ProjectSelect(props: ProjectSelectProps) {
  const fallback = <Button disabled variant="secondary" aria-label={props.label}>Selection unavailable{props.value ? ` · ${props.value}` : ""}</Button>;
  return <Slot id={PROJECT_SELECT_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}
export function CycleSelect(props: CycleSelectProps) {
  const fallback = <Button disabled variant="secondary" aria-label={props.label ?? props.placeholder}>Selection unavailable{props.selectedLabel || props.value ? ` · ${props.selectedLabel || props.value}` : ""}</Button>;
  return <Slot id={CYCLE_SELECT_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}
/** A labelled checkbox, with an optional line under the label. `data-*` props land on the input. */
export function CheckField({ label, hint, checked, onChange, className = "", ...data }: {
  label: ReactNode;
  hint?: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  className?: string;
} & { [attribute: `data-${string}`]: string | boolean | undefined }) {
  return (
    <label className={`flex w-fit cursor-pointer gap-2 text-[13px] text-fg ${hint ? "items-start" : "items-center"} ${className}`}>
      <input
        type="checkbox"
        {...data}
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className={`${hint ? "mt-0.5 " : ""}size-3.5 cursor-pointer accent-[var(--accent-fill)]`}
      />
      {hint ? <span>{label}<span className="block text-xs text-fg-secondary">{hint}</span></span> : label}
    </label>
  );
}

export function CustomFieldControl(props: ControlProps) {
  const fallback = <p className="text-sm text-fg-muted">{props.field.name}: field unavailable. Saved value is preserved.</p>;
  return <Slot id={FIELD_CONTROL_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}
