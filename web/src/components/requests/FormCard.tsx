import { Link } from "@tanstack/react-router";
import { ClipboardList } from "lucide-react";
import { RoutePath } from "../../lib/constants";
import type { PortalFormCard, PortalProjectRef } from "../../lib/types";

/** One request form as a card (Portal and My Work); the project key shows only when several projects are in view. */
export function FormCard({
  form,
  project,
  showProject = false,
}: {
  form: PortalFormCard;
  project: PortalProjectRef;
  showProject?: boolean;
}) {
  return (
    <li>
      <Link
        to={RoutePath.portalForm}
        params={{ formId: form.id }}
        className="flex h-full flex-col gap-1 rounded-lg border border-subtle bg-surface/40 p-3 hover:border-emphasis hover:bg-surface focus-visible:outline-2 focus-visible:outline-focus"
      >
        <span className="flex items-center gap-1.5 text-[13px] font-medium text-heading">
          <ClipboardList size={14} className="shrink-0 text-accent-text" aria-hidden />
          {form.name}
          {showProject && (
            <span className="ml-auto shrink-0 rounded bg-elevated px-1 font-mono text-[11px] text-fg-secondary">
              {project.key}
            </span>
          )}
        </span>
        {form.description && (
          <span className="line-clamp-2 text-xs text-fg-muted">{form.description}</span>
        )}
      </Link>
    </li>
  );
}

/** The grid both surfaces lay cards out in. `auto-fit` rather than a fixed
 *  column count, so one form does not stretch across the page and six do not
 *  crush at a narrow width. */
export function FormCardGrid({ children }: { children: React.ReactNode }) {
  return (
    <ul className="grid gap-2 [grid-template-columns:repeat(auto-fit,minmax(15rem,1fr))]">
      {children}
    </ul>
  );
}
