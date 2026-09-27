import { api, definePlugin, type QuerySource, Entity } from "@radd/plugin-sdk";
import type { Project } from "./types";
import { ProjectSelect } from "./ProjectSelect";
import { ProjectPicker } from "./ProjectPicker";
import { PROJECT_SELECT_SLOT, PROJECT_PICKER_SLOT, type ProjectSelectProps, type ProjectPickerProps } from "./picker-contract";
const firstProjectSource: QuerySource<Project[]> = {key: "projects.first", meta: {entities: [Entity.project, Entity.role, Entity.accessGrant, Entity.member]},
  fetch: (_args, signal) => api.get<Project[]>("/projects", {signal, query: {limit: "1"}}),
};
export default definePlugin({ querySources: [firstProjectSource], contributions: [
  { id: "select", slot: PROJECT_SELECT_SLOT, toggleable: false, render: props => <ProjectSelect {...(props as unknown as ProjectSelectProps)} /> },
  { id: "picker", slot: PROJECT_PICKER_SLOT, toggleable: false, render: props => <ProjectPicker {...(props as unknown as ProjectPickerProps)} /> },
] });
