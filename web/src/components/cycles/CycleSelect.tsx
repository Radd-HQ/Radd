import { Slot, Button, Modal } from "@radd/plugin-sdk";
import { CYCLE_SELECT_SLOT, CYCLE_CHOICES_SLOT, type CycleSelectProps, type CycleChoicesProps } from "../../../../server/src/radd/modules/cycles/ui/src/picker-contract";
/** Transitional slot adapters; Cycles owns controls, scope and transport. */
export function CycleSelect(props: CycleSelectProps) {
  const fallback = <Button disabled variant="secondary" aria-label={props.label ?? props.placeholder}>Selection unavailable{props.selectedLabel || props.value ? ` · ${props.selectedLabel || props.value}` : ""}</Button>;
  return <Slot id={CYCLE_SELECT_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}
export function CycleChoices(props: CycleChoicesProps) {
  const fallback = <Modal title="Selection unavailable" onClose={props.onClose}><p>This picker is unavailable. Saved values are preserved.</p></Modal>;
  return <Slot id={CYCLE_CHOICES_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}
