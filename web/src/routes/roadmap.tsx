import { Navigate, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { RoutePath } from "../lib/constants";
import { useProjectByKey } from "../lib/hooks";
import { viewsPageQuery } from "../lib/queries";
import { ViewType } from "../lib/types";
import { Spinner } from "../components/Spinner";
import { QueryError } from "../components/QueryError";

/**
 * /p/$projectKey/roadmap — LEGACY path (specs 19/77/78). Roadmaps are saved
 * views since spec 79 (rendered by routes/view.tsx via RoadmapSurface): this
 * redirects to the project's first roadmap-type view, else the project home.
 * The route stays registered so old links keep working.
 */
export function RoadmapPage() {
  const { projectKey = "" } = useParams({ strict: false });
  const { project } = useProjectByKey(projectKey);
  const views = useQuery({ ...viewsPageQuery({ projectId: project?.id, includeGlobal: false, viewType: ViewType.roadmap }, "", 0, 1), enabled: Boolean(project) });

  if (project === undefined || (Boolean(project) && views.isPending)) {
    return <Spinner label="Loading roadmap…" />;
  }
  if (project === null) {
    return <div className="p-10 text-sm text-fg-muted">Project “{projectKey}” not found.</div>;
  }
  if (views.isError) return <div className="p-10"><QueryError label="views" error={views.error} /></div>;
  const roadmap = views.data?.rows[0];
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
