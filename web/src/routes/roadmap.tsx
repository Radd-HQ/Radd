import { Navigate, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { RoutePath } from "../lib/constants";
import { useProjectByKey } from "../lib/hooks";
import { viewsQuery } from "../lib/queries";
import { ViewType } from "../lib/types";
import { Spinner } from "../components/Spinner";

/**
 * /p/$projectKey/roadmap — LEGACY path (specs 19/77/78). Roadmaps are saved
 * views since spec 79 (rendered by routes/view.tsx via RoadmapSurface): this
 * redirects to the project's first roadmap-type view, else the project home.
 * The route stays registered so old links keep working.
 */
export function RoadmapPage() {
  const { projectKey = "" } = useParams({ strict: false });
  const { project } = useProjectByKey(projectKey);
  const views = useQuery(viewsQuery());

  if (project === undefined || views.isPending) {
    return <Spinner label="Loading roadmap…" />;
  }
  if (project === null) {
    return <div className="p-10 text-sm text-fg-muted">Project “{projectKey}” not found.</div>;
  }
  const roadmap = (views.data ?? []).find(
    (view) => view.project_id === project.id && view.view_type === ViewType.roadmap,
  );
  if (roadmap) {
    return (
      <Navigate
        to={RoutePath.projectView}
        params={{ projectKey, viewId: roadmap.id }}
        replace
      />
    );
  }
  return <Navigate to={RoutePath.project} params={{ projectKey }} replace />;
}
