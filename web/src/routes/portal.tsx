import { useQuery } from "@tanstack/react-query";
import { ClipboardList, ConciergeBell } from "lucide-react";
import { errorMessage } from "../lib/api";
import { portalFormsQuery } from "../lib/queries";
import { type PortalGroup } from "../lib/types";
import { EmptyState } from "../components/EmptyState";
import { Spinner } from "../components/Spinner";
import { FormCard, FormCardGrid } from "../components/requests/FormCard";
import { MyRequests } from "../components/requests/RequestSection";

/**
 * Requester portal (spec 73) — route `/portal`, visible to every signed-in
 * user. The directory of intake forms AVAILABLE TO the visitor: public forms
 * plus forms shared with them or their teams, grouped by project. A card
 * opens the portal submit page.
 */
export function PortalPage() {
  const groups = useQuery(portalFormsQuery);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-10">
      <header className="flex flex-col gap-2 border-b border-subtle pb-4">
        <div className="flex items-center gap-2 text-accent-text">
          <ConciergeBell size={18} aria-hidden />
          <span className="text-[11px] font-medium uppercase tracking-wide">Portal</span>
        </div>
        <h1 className="text-xl font-semibold text-heading">Submit a request</h1>
        <p className="text-sm text-fg-secondary">
          Request forms available to you — public forms plus forms shared with you or your teams.
        </p>
      </header>

      {/* Forms FIRST (RADD-804). The page is called "Submit a request"; a
          directory whose directory sits below the fold is not one. */}
      {groups.isPending ? (
        <Spinner label="Loading forms…" />
      ) : groups.isError ? (
        <p className="text-sm text-red-400">
          Could not load the portal: {errorMessage(groups.error)}
        </p>
      ) : groups.data.length === 0 ? (
        <EmptyState
          icon={ClipboardList}
          message="No request forms are available to you yet — ask a project admin to share one."
        />
      ) : (
        groups.data.map((group) => <ProjectGroup key={group.project.id} group={group} />)
      )}

      <MyRequests />
    </div>
  );
}

/** One project's block: name + key chip, then a card per eligible form. */
function ProjectGroup({ group }: { group: PortalGroup }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="flex items-center gap-2 text-sm font-medium text-fg">
        <span className="rounded bg-elevated px-1 font-mono text-[11px] text-fg-secondary">
          {group.project.key}
        </span>
        {group.project.name}
      </h2>
      <FormCardGrid>
        {group.forms.map((form) => (
          <FormCard key={form.id} form={form} project={group.project} />
        ))}
      </FormCardGrid>
    </section>
  );
}
