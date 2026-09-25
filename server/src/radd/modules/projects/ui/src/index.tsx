import { definePlugin } from "@radd/plugin-sdk";
import { ProjectSelect } from "./ProjectSelect";
import { ProjectPicker } from "./ProjectPicker";
import { PROJECT_SELECT_SLOT, PROJECT_PICKER_SLOT, type ProjectSelectProps, type ProjectPickerProps } from "./picker-contract";
export default definePlugin({ contributions: [
  { id: "select", slot: PROJECT_SELECT_SLOT, toggleable: false, render: props => <ProjectSelect {...(props as unknown as ProjectSelectProps)} /> },
  { id: "picker", slot: PROJECT_PICKER_SLOT, toggleable: false, render: props => <ProjectPicker {...(props as unknown as ProjectPickerProps)} /> },
] });
