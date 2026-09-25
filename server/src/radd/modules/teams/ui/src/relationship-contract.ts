import type { ReactNode } from "react";
export const TEAM_SELECT_SLOT = "teams.relationship.select";
export const TEAM_CHOICES_SLOT = "teams.relationship.choices";
export const TEAM_AUDIENCE_SLOT = "teams.relationship.audience";
export interface TeamSelectProps {
  value: string; onChange: (id: string) => void; label?: string; selectedLabel?: string;
  placeholder?: string; emptyLabel?: string; disabled?: boolean; title?: string; error?: string; size?: "sm" | "md";
}
export interface TeamChoicesProps {
  selected?: string[]; emptyLabel?: string; onSelect: (id: string) => void; onClose: () => void; footer?: ReactNode;
}
export interface TeamAudienceProps {
  value: string[]; onChange?: (ids: string[]) => void;
  /** The consuming feature owns the meaning of empty and restricted selections. */
  emptyText?: string; hint?: string; addLabel?: string;
}
