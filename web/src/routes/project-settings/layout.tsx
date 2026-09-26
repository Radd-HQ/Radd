import { Link, Navigate, Outlet, useParams } from "@tanstack/react-router";
import { SlotId } from "@radd/plugin-sdk";
import { RoutePath } from "../../lib/constants";
import { useProjectByKey, usePermissions } from "../../lib/hooks";
import { Permission, SettingScope } from "../../lib/types";
import { useProjectSettingsNav } from "../../lib/project-settings-nav";
import { ProjectIdentityCard } from "../../components/projects/ProjectIdentityCard";
import { DeleteProjectCard } from "../../components/projects/DeleteProjectCard";
import { ScopedSettingsEditor } from "../../components/settings/ScopedSettingsEditor";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { ContributedPage } from "../../components/shell/ContributedPage";
import { Spinner } from "../../components/Spinner";
import { IssueTypesSettingsPage } from "./issue-types";
import { ScreensSettingsPage } from "./screens";
import { ProjectAccessSettingsPage } from "./projects";
import { StatesSettingsPage } from "./states";
import { FormsSettingsPage } from "./forms";
import { ProjectTimeloggingSettingsPage } from "./timelogging";

/** Resolve the URL's `$projectKey` to its project (shared by layout + wrappers). */
function useUrlProject() {
  const { projectKey = "" } = useParams({ strict: false });
  return { projectKey, ...useProjectByKey(projectKey) };
}

const navLinkClasses =
  "flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-fg-secondary hover:bg-elevated " +
  "hover:text-heading focus-visible:outline-2 focus-visible:outline-focus " +
  "[&.active]:bg-elevated [&.active]:text-heading";

/**
 * Project-settings shell (spec 50): the sub-nav lists the sections this person may manage in
 * THIS project — the host's tabs and the pages enabled plugins contribute (RADD-1396, e.g. the
 * slas plugin's SLAs) — and the section renders in the Outlet. The project key/name is shown in
 * the header; an unresolved key renders empty.
 */
export function ProjectSettingsLayout() {
  const { projectKey, project } = useUrlProject();
  const visible = useProjectSettingsNav(project);

  if (project === undefined) {
    return <Spinner label="Loading settings…" />;
  }

  if (project === null) {
    return (
      <div className="flex h-full flex-col">
        <header className="border-b border-subtle px-6 py-3.5">
          <h1 className="text-sm font-semibold text-heading">Project settings</h1>
        </header>
        <div className="p-10 text-sm text-fg-muted">Project “{projectKey}” not found.</div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-subtle px-6 py-3.5">
        <span className="rounded bg-elevated px-1.5 py-0.5 font-mono text-xs text-fg">
          {project.key}
        </span>
        <h1 className="text-sm font-semibold text-heading">{project.name}</h1>
        <span className="text-xs text-fg-muted">Project settings</span>
        {project.description && (
          <p data-project-description className="basis-full truncate text-xs text-fg-secondary">
            {project.description}
          </p>
        )}
      </header>
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <nav
          aria-label="Project settings sections"
          className="w-full shrink-0 overflow-x-auto border-b border-subtle p-2 lg:w-44 lg:border-b-0 lg:border-r"
        >
          <ul className="flex whitespace-nowrap gap-0.5 lg:flex-col">
            {visible.map(({ to, label, icon: Icon, plugin }) => (
              <li key={to}>
                <Link to={to} params={{ projectKey }} className={navLinkClasses} data-plugin-nav={plugin}>
                  <Icon size={14} aria-hidden />
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </div>
    </div>
  );
}

/** Land on an available section, including access-only delegates. */
export function ProjectSettingsIndex() {
  const { projectKey, project } = useUrlProject();
  const first = useProjectSettingsNav(project)[0];
  if (!project) return <Spinner label="Loading settings…" />;
  return first ? <Navigate to={first.to} params={{ projectKey }} replace />
    : <p className="p-4 text-sm text-fg-muted">You have no project settings to manage here.</p>;
}

/**
 * Section wrappers: resolve `$projectKey`→project and pass its id to the reused
 * settings page, which reads the project from that id (no in-page picker).
 */
export function ProjectGeneralSettings() {
  const { project } = useUrlProject();
  const perms = usePermissions();
  return (
    <SettingsPage
      title="General"
      description="The project's name and description, then its overrides for the cascaded settings that don't belong to a tab of their own. Each of those falls back to the instance default (Settings → General)."
    >
      {project ? (
        <div className="flex flex-col gap-6">
          {/* RADD-1009: keyed on the project so a route change resets the drafts. */}
          <ProjectIdentityCard
            key={project.id}
            project={project}
            canManage={perms.project(project, Permission.projectManage)}
          />
          {/* RADD-930: the REMAINDER, not everything. The release states, the
              working week and plugins' own opt-ins now declare their own tabs, and the
              enforcement mode declares Workflow — which also retires the
              hand-written `key !== WORKFLOW_TRANSITION_MODE_KEY` exclude that used
              to keep a second, free-text copy of that dropdown off this page. */}
          <ScopedSettingsEditor
            scope={SettingScope.project}
            scopeId={project.id}
            general
            emptyLabel="Every cascaded setting for this project lives on one of the tabs beside this one."
          />
          {/* RADD-1174: the GLOBAL atom, so a delegated project admin never sees it. */}
          {perms.global(Permission.projectDelete) && <DeleteProjectCard project={project} />}
        </div>
      ) : null}
    </SettingsPage>
  );
}

export function ProjectAccessSettings() {
  const { project } = useUrlProject();
  return <ProjectAccessSettingsPage projectId={project?.id} />;
}

export function ProjectWorkflowSettings() {
  const { project } = useUrlProject();
  return <StatesSettingsPage projectId={project?.id} />;
}

export function ProjectTypesSettings() {
  const { project } = useUrlProject();
  return <IssueTypesSettingsPage projectId={project?.id} />;
}

export function ProjectScreensSettings() {
  const { project } = useUrlProject();
  return <ScreensSettingsPage projectId={project?.id} />;
}

/** RADD-1290: releases are a project page now; the old settings address forwards. */
export function ProjectReleasesSettings() {
  const { projectKey = "" } = useParams({ strict: false });
  return <Navigate to={RoutePath.projectReleases} params={{ projectKey }} replace />;
}

export function ProjectFormsSettings() {
  const { project } = useUrlProject();
  return <FormsSettingsPage projectId={project?.id} />;
}

export function ProjectTimeloggingSettings() {
  const { project } = useUrlProject();
  return <ProjectTimeloggingSettingsPage projectId={project?.id} />;
}

/** A page a plugin contributes to project settings (RADD-1396): the `project.settings.page`
 *  contribution matched on the URL's segment, handed the project. Its nav entry lists it. */
export function ProjectSettingsPluginPage() {
  const { project } = useUrlProject();
  const { _splat: segment = "" } = useParams({ strict: false });
  if (!project) return <Spinner label="Loading settings…" />;
  return <ContributedPage slot={SlotId.projectSettingsPage} match={segment} props={{ project }} />;
}
