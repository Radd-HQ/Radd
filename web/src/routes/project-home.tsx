import { Navigate, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { RoutePath } from "../lib/constants";
import { useProjectByKey } from "../lib/hooks";
import { viewsQuery } from "../lib/queries";
import { ViewType } from "../lib/types";
import { Spinner } from "../components/Spinner";

/**
 * /p/$projectKey — the project landing. Projects have no special surfaces
 * anymore, only views (seeded with Board/List/Planning at creation), so this
 * simply opens the project's first visible view (server order: position →
 * name). No views left = an empty-state hint; nothing is resolved or stored.
 */
export function ProjectHomePage() {
  const { projectKey = "" } = useParams({ strict: false });
  const { project } = useProjectByKey(projectKey);
  const views = useQuery(viewsQuery());

  if (project === undefined || views.isPending) {
    return <Spinner label="Loading project…" />;
  }
  if (project === null) {
    return <div className="p-10 text-sm text-fg-muted">Project “{projectKey}” not found.</div>;
  }
  const first = (views.data ?? []).find(
    (view) => view.project_id === project.id && view.view_type !== ViewType.queue,
  );
  if (first) {
    return (
      <Navigate
        to={RoutePath.projectView}
        params={{ projectKey, viewId: first.id }}
        replace
      />
    );
  }
  return (
    <div className="p-10 text-sm text-fg-muted">
      {project.name} has no views yet — create one from the sidebar (+ New view).
    </div>
  );
}
