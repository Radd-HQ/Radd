import { useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { History, Info, X } from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { Permission } from "../../lib/types";

/**
 * What a settings page is ABOUT, for its "Change history" footer link (spec
 * 123, RADD-1171): the entity types it edits and, for a project's settings,
 * the project. The link opens the audit log with exactly those filters.
 */
export interface SettingsHistoryContext {
  /** Entity types this page edits (`role`, `field`, `storage_host`…). */
  entities?: string[];
  /** The project a per-project settings page belongs to. */
  projectId?: string;
}

interface SettingsPageProps {
  title: string;
  description?: string;
  /** Right-aligned header affordances (hidden by callers when role-gated). */
  actions?: ReactNode;
  /** A dismissible explanatory callout under the header. */
  info?: ReactNode;
  /** The audit context for the footer link; omit on pages with no trail (profile, monitoring). */
  history?: SettingsHistoryContext;
  children: ReactNode;
}

/** Common frame for a settings section: heading, blurb, actions, content. */
export function SettingsPage({ title, description, actions, info, history, children }: SettingsPageProps) {
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
      {history && <ChangeHistoryLink history={history} />}
    </div>
  );
}

/**
 * The footer link every settings page carries (RADD-1171): "who changed what
 * to what" for the context being viewed, one click away, filters preset.
 * Hidden for a viewer the audit log would refuse (no `global.manage`; for a
 * project page, no `project.manage` anywhere), the way the nav hides tabs.
 */
export function ChangeHistoryLink({ history }: { history: SettingsHistoryContext }) {
  const perms = usePermissions();
  const allowed =
    perms.global(Permission.globalManage) ||
    (Boolean(history.projectId) && perms.anyProject(Permission.projectManage));
  if (!allowed) return null;
  return (
    <footer className="mt-8 border-t border-subtle/60 pt-4" data-settings-history>
      <Link
        to={RoutePath.settingsAudit}
        search={{
          entity: history.entities?.length ? history.entities.join(",") : undefined,
          project: history.projectId,
        }}
        className="inline-flex items-center gap-1.5 text-[13px] text-accent-text hover:text-accent-text-strong"
      >
        <History size={14} aria-hidden />
        Change history for this page
      </Link>
    </footer>
  );
}

/** Dismissible info callout — explains what a settings section does. */
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
