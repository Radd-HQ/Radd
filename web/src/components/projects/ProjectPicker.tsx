import { Slot, Modal } from "@radd/plugin-sdk";
import { PROJECT_PICKER_SLOT, type ProjectPickerProps } from "@radd-plugin-ui/projects/picker-contract";
/** The host's typed entry to the Projects picker modal, rendered through its slot. */
export function ProjectPicker(props: ProjectPickerProps) {
  const fallback = <Modal title={props.title} onClose={props.onClose}><p>This picker is unavailable. Saved values are preserved.</p></Modal>;
  return <Slot id={PROJECT_PICKER_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}
