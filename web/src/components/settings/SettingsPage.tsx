import { useState, type ReactNode } from "react";
import { Info, X } from "lucide-react";

interface SettingsPageProps {
  title: string;
  description?: string;
  /** Right-aligned header affordances (hidden by callers when role-gated). */
  actions?: ReactNode;
  /** A dismissible explanatory callout under the header (OtherTracker-style). */
  info?: ReactNode;
  children: ReactNode;
}

/** Common frame for a settings section: heading, blurb, actions, content. */
export function SettingsPage({ title, description, actions, info, children }: SettingsPageProps) {
  return (
    <div className="px-8 py-8">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-heading">{title}</h2>
          {description && <p className="mt-1 text-[13px] text-fg-muted">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {info && <InfoBanner>{info}</InfoBanner>}
      {children}
    </div>
  );
}

/** Dismissible info callout (OtherTracker-style) — explains what a settings section does. */
export function InfoBanner({ children }: { children: ReactNode }) {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;
  return (
    <div className="mb-5 flex items-start gap-2.5 rounded-lg border border-accent/25 bg-accent/5 px-3.5 py-2.5 text-[13px] text-fg">
      <Info size={15} className="mt-0.5 shrink-0 text-accent-text" aria-hidden />
      <div className="min-w-0 flex-1">{children}</div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="Dismiss"
        className="shrink-0 rounded p-0.5 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
      >
        <X size={14} aria-hidden />
      </button>
    </div>
  );
}

/** Shared table cell/head styling for settings tables. */
export const settingsTableClasses = {
  table: "w-full border-separate border-spacing-0 text-left text-[13px]",
  head: "border-b border-subtle px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-fg-faint",
  cell: "border-b border-subtle/60 px-3 py-2.5 text-fg",
} as const;
