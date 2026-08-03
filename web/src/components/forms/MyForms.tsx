import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ConciergeBell } from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { portalFormsQuery } from "../../lib/queries";

/**
 * The request forms this person may submit (RADD-786).
 *
 * On My Work, because that is where everyone lands — `RoutePath.home` renders
 * it, and both the password login and the spec-110 SSO callback redirect there.
 * For someone whose whole relationship with Radd is "file a request", My Work
 * otherwise shows nothing they can act on, and the forms sit behind a Portal
 * entry they have no reason to have found.
 *
 * Renders NOTHING when the list is empty. For a staffer with no shared forms
 * this would be a permanent empty card on the busiest page in the product; for
 * a requester it is the only thing on the page that does anything.
 *
 * Fed by `GET /portal/forms`, which already answers by ELIGIBILITY rather than
 * membership — public forms plus those shared with the actor or their teams —
 * so there is no new endpoint and no second opinion about who may see what.
 */
export function MyForms() {
  const groups = useQuery(portalFormsQuery);
  const rows = (groups.data ?? []).flatMap((group) =>
    group.forms.map((form) => ({ form, project: group.project })),
  );

  if (groups.isPending || rows.length === 0) return null;

  return (
    <section className="flex flex-col gap-2" aria-label="Submit a request">
      <h2 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-fg-muted">
        <ConciergeBell size={12} aria-hidden />
        Submit a request
      </h2>
      <ul className="flex flex-col rounded-lg border border-subtle bg-surface">
        {rows.map(({ form, project }) => (
          <li key={form.id} className="border-b border-subtle/60 last:border-b-0">
            <Link
              to={RoutePath.portalForm}
              params={{ formId: form.id }}
              className="flex items-baseline gap-2 px-3 py-2 text-[13px] hover:bg-elevated"
            >
              <span className="shrink-0 rounded bg-elevated px-1 font-mono text-[11px] text-fg-secondary">
                {project.key}
              </span>
              <span className="min-w-0 flex-1 truncate text-fg">{form.name}</span>
              {form.description && (
                <span className="hidden min-w-0 max-w-[45%] truncate text-[11px] text-fg-muted @2xl:block">
                  {form.description}
                </span>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
