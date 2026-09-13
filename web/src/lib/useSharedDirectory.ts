import { useDirectory } from "./useDirectory";
import { dashboardsPageQuery, viewsPageQuery, SHARED_DIRECTORY_PAGE_SIZE, type ViewDirectoryScope } from "./queries/shared-directories";


export const useViewDirectory = (scope: ViewDirectoryScope = {}) =>
  useDirectory(JSON.stringify(scope), SHARED_DIRECTORY_PAGE_SIZE, (q, page) => viewsPageQuery(scope, q, page));
export const useDashboardDirectory = (enabled = true) => useDirectory("dashboards", SHARED_DIRECTORY_PAGE_SIZE, dashboardsPageQuery, { enabled });
