/**
 * The sidebar's Dashboards section, as the host draws it: the reader's dashboards (a searchable,
 * paged directory) and the New dashboard dialog. The section chrome stays the shell's.
 */
import { usePagedDirectory } from "@radd/plugin-sdk";
import { SIDEBAR_PAGE_SIZE, dashboardsPageQuery } from "./queries";

export { DashboardModal } from "./DashboardModal";

/** `enabled` false holds the directory back (a visitor has no dashboards). */
export function useDashboardDirectory(enabled = true) {
  return usePagedDirectory("dashboards", dashboardsPageQuery, { pageSize: SIDEBAR_PAGE_SIZE, enabled });
}
