import { Link, useParams } from "@tanstack/react-router";
import { BarChart3, ChevronDown, ChevronRight, Plus, Rocket, Settings } from "lucide-react";
import { RoutePath } from "../../lib/constants";
import type { PermissionChecks } from "../../lib/hooks";
import { Permission, ViewType, type Project } from "../../lib/types";
import { useQuery } from "@tanstack/react-query";
import { viewQuery } from "../../lib/queries/shared-directories";
import { useViewDirectory } from "../../lib/useSharedDirectory";
import { SidebarDirectory } from "./SidebarDirectory";
import { ProjectFormLinks, ViewRowContent, subLinkClasses } from "./SidebarRows";

/** A project tree also renders independently for the current route's context. */
export function SidebarProjectRow({ project, expanded, permissions, onToggle, onNewItem, onNewView }: {
  project: Project; expanded: boolean; permissions: PermissionChecks;
  onToggle: () => void; onNewItem: () => void; onNewView: () => void;
}) {
  return (
                <li>
                  <div className="group/project relative flex items-center">
                    <button
                      type="button"
                      onClick={onToggle}
                      aria-expanded={expanded}
                      aria-label={`${expanded ? "Collapse" : "Expand"} ${project.key}`}
                      className="ml-0.5 rounded p-0.5 text-fg-faint hover:bg-overlay hover:text-fg cursor-pointer"
                    >
                      {expanded ? (
                        <ChevronDown size={11} aria-hidden />
                      ) : (
                        <ChevronRight size={11} aria-hidden />
                      )}
                    </button>
                    <Link
                      to={RoutePath.project}
                      params={{ projectKey: project.key }}
                      activeOptions={{ exact: true }}
                      className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1.5 pr-7 text-[13px] text-fg-secondary hover:bg-overlay hover:text-heading focus-visible:outline-2 focus-visible:outline-focus"
                    >
                      <span className="rounded bg-elevated px-1 font-mono text-[11px] text-fg-secondary">
                        {project.key}
                      </span>
                      <span className="truncate">{project.name}</span>
                    </Link>
                    {permissions.project(project, Permission.itemCreate) && (
                      <button
                        type="button"
                        onClick={onNewItem}
                        aria-label={`New issue in ${project.key}`}
                        title={`New issue in ${project.key}`}
                        className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-1 text-fg-faint opacity-0 transition-opacity hover:bg-overlay hover:text-fg focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-focus group-hover/project:opacity-100 cursor-pointer"
                      >
                        <Plus size={12} />
                      </button>
                    )}
                  </div>

                  {/* Per-project section: the project's VIEWS (projects ship with
                      Board/List/Planning/Roadmap as plain seeded views — no
                      special entries), then the non-view surfaces. Folded by
                      default; the current route's project auto-expands. */}
                  {expanded && (
                  <ul className="pb-1">
                    <li><ProjectViewLinks project={project} /></li>
                    <li>
                      <Link
                        to={RoutePath.projectReports}
                        params={{ projectKey: project.key }}
                        className={subLinkClasses}
                      >
                        <BarChart3 size={12} aria-hidden />
                        Reports
                      </Link>
                    </li>
                    <li>
                      <Link
                        to={RoutePath.projectReleases}
                        params={{ projectKey: project.key }}
                        className={subLinkClasses}
                      >
                        <Rocket size={12} aria-hidden />
                        Releases
                      </Link>
                    </li>
                    {(permissions.project(project, Permission.stateManage) ||
                      permissions.project(project, Permission.projectManage) ||
                      permissions.project(project, Permission.formManage) ||
                      permissions.project(project, Permission.releaseUpdate) ||
                      permissions.project(project, Permission.memberCreate) ||
                      permissions.project(project, Permission.memberDelete) ||
                      permissions.global(Permission.roleUpdate) ||
                      permissions.global(Permission.slaUpdate)) && (
                      <li>
                        <Link
                          to={RoutePath.projectSettings}
                          params={{ projectKey: project.key }}
                          className={subLinkClasses}
                        >
                          <Settings size={12} aria-hidden />
                          Settings
                        </Link>
                      </li>
                    )}
                    {permissions.project(project, Permission.itemRead) && (
                      <li>
                        <button
                          type="button"
                          onClick={onNewView}
                          className={`${subLinkClasses} w-full cursor-pointer text-left text-fg-faint!`}
                        >
                          <Plus size={12} aria-hidden />
                          New view
                        </button>
                      </li>
                    )}
                    {permissions.project(project, Permission.formManage) && (
                      <ProjectFormLinks project={project} />
                    )}
                  </ul>
                  )}
                </li>
  );
}


function ProjectViewLinks({ project }: { project: Project }) {
  const directory = useViewDirectory({ projectId: project.id, includeGlobal: false, excludeType: ViewType.queue });
  const { viewId = "" } = useParams({ strict: false });
  const current = useQuery(viewQuery(viewId));
  const contextView = !directory.filter && current.data?.project_id === project.id
    && current.data.view_type !== ViewType.queue && !directory.rows.some(row => row.id === viewId)
    ? current.data : null;
  return <SidebarDirectory directory={directory} label={`${project.key} views`}>
    {contextView && <div className="border-b border-subtle pb-1">
      <span className="px-2 text-[11px] text-fg-muted">Current view</span>
      <Link to={RoutePath.projectView} params={{ projectKey: project.key, viewId: contextView.id }} className={subLinkClasses}>
        <ViewRowContent view={contextView} small />
      </Link>
    </div>}
    <ul>{directory.rows.map(view => <li key={view.id}>
      <Link to={RoutePath.projectView} params={{ projectKey: project.key, viewId: view.id }} className={subLinkClasses}>
        <ViewRowContent view={view} small />
      </Link>
    </li>)}</ul>
  </SidebarDirectory>;
}
