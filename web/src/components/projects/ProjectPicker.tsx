import { Slot, Modal } from "@radd/plugin-sdk";
import { PROJECT_PICKER_SLOT, type ProjectPickerProps } from "../../../../server/src/radd/modules/projects/ui/src/picker-contract";
/** Transitional slot adapter; the owner contributes this modal. */
export function ProjectPicker(props: ProjectPickerProps) {
  const fallback = <Modal title={props.title} onClose={props.onClose}><p>This picker is unavailable. Saved values are preserved.</p></Modal>;
  return <Slot id={PROJECT_PICKER_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}
