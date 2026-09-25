import type { Project } from "./types";
export const PROJECT_SELECT_SLOT = "projects.select";
export const PROJECT_PICKER_SLOT = "projects.picker";
export interface ProjectSelectProps {
  value: string; onChange: (id: string, project: Project | null) => void;
  label?: string; emptyLabel?: string | null; emptyValue?: string;
  valueBy?: "id" | "key"; permission?: string; disabled?: boolean; hint?: string;
}
export interface ProjectPickerProps {
  title: string; permission?: string; onSelect: (project: Project) => void; onClose: () => void;
  selectedId?: string; emptyLabel?: string; onClear?: () => void;
}
