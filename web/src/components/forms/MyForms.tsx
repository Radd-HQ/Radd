import { useQuery } from "@tanstack/react-query";
import { ConciergeBell } from "lucide-react";
import { portalFormsQuery } from "../../lib/queries";
import { FormCard, FormCardGrid } from "../requests/FormCard";

/**
 * The request forms this person may submit, on My Work (where every login lands). Renders nothing when
 * empty. `GET /portal/forms` already answers by eligibility, so no second visibility rule lives here.
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
      {/* The SAME cards the Submission Portal shows (RADD-804). This was a bare
          list, which made the two surfaces draw one thing two ways — the
          RADD-799 complaint, one section over. */}
      <FormCardGrid>
        {rows.map(({ form, project }) => (
          <FormCard
            key={form.id}
            form={form}
            project={project}
            // My Work spans every project someone can file into, so the key
            // earns its place here in a way it does not on a per-project block.
            showProject={new Set(rows.map((r) => r.project.id)).size > 1}
          />
        ))}
      </FormCardGrid>
    </section>
  );
}
