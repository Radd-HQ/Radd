import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon: LucideIcon;
  message: string;
  /** Optional call-to-action (hidden for users who lack the permission). */
  action?: ReactNode;
}

/** Quiet empty-state block used by lists/tables when there are no rows yet. */
export function EmptyState({ icon: Icon, message, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-subtle py-14 text-fg-muted">
      <Icon size={24} aria-hidden className="text-fg-faint" />
      <p className="text-sm">{message}</p>
      {action}
    </div>
  );
}
