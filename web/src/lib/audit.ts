/**
 * The audit ledger's client-side seams (spec 123): the URL filter shape the
 * route validates, and where an entity in the trail LINKS to.
 *
 * Both are here rather than in the page so a settings page can build a
 * deep link (RADD-1171: "Change history for this page") with the same
 * vocabulary the page reads, and so the link table has one owner.
 */
import type { AuditEntry, AuditSourceValue } from "./types";
import { RoutePath } from "./constants";
import { pagePermalink } from "./page-links";

/** Every filter rides in the URL — short inline params, shareable as they are. */
export interface AuditSearch {
  project?: string;
  entity?: string;
  entity_id?: string;
  actor?: string;
  field?: string;
  source?: AuditSourceValue;
  from?: string;
  to?: string;
  q?: string;
  noise?: boolean;
}

const SOURCES = new Set(["people", "automations", "system"]);

function str(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

export function parseAuditSearch(search: Record<string, unknown>): AuditSearch {
  const source = str(search.source);
  return {
    project: str(search.project),
    entity: str(search.entity),
    entity_id: str(search.entity_id),
    actor: str(search.actor),
    field: str(search.field),
    source: source && SOURCES.has(source) ? (source as AuditSourceValue) : undefined,
    from: str(search.from),
    to: str(search.to),
    q: str(search.q),
    noise: search.noise === true || search.noise === "true" ? true : undefined,
  };
}

/** A router `to` + params for the entity a row is about, or null when nothing links. */
export interface AuditLink {
  to: string;
  params?: Record<string, string>;
  search?: Record<string, string | number>;
}

/** Settings pages by entity type — the instance-scoped ones. */
const SETTINGS_BY_ENTITY: Record<string, string> = {
  user: RoutePath.settingsUsers,
  service_account: RoutePath.settingsServiceAccounts,
  role: RoutePath.settingsRoles,
  field: RoutePath.settingsFields,
  label: RoutePath.settingsLabels,
  link_type: RoutePath.settingsLinkTypes,
  cycle: RoutePath.settingsCycles,
  cycle_series: RoutePath.settingsCycles,
  team: RoutePath.settingsTeams,
  webhook_endpoint: RoutePath.settingsWebhooks,
  automation_rule: RoutePath.settingsAutomations,
  canned_response: RoutePath.settingsCanned,
  work_category: RoutePath.settingsTimelogging,
  sso_provider: RoutePath.settingsSignIn,
  ai_provider: RoutePath.settingsAi,
  ai_role: RoutePath.settingsAi,
  ai_preset: RoutePath.settingsAi,
  storage_host: RoutePath.settingsStorage,
  storage_rule: RoutePath.settingsStorage,
  mail_source: RoutePath.settingsEmail,
  mail_sender: RoutePath.settingsEmail,
  mail_rule: RoutePath.settingsEmail,
  // RADD-1262: the per-kind paths redirect to the right tab of Version control.
  forgejo_connection: RoutePath.settingsForgejo,
  forgejo_repo: RoutePath.settingsForgejo,
  github_connection: RoutePath.settingsGithub,
  github_repo: RoutePath.settingsGithub,
  gitlab_connection: RoutePath.settingsGitlab,
  gitlab_repo: RoutePath.settingsGitlab,
  vcs_user_link: RoutePath.settingsVcs,
  jira_connection: RoutePath.settingsJiraImport,
  confluence_connection: RoutePath.settingsConfluenceImport,
  backup_schedule: RoutePath.settingsBackups,
  plugin: RoutePath.settingsPlugins,
  page_space: RoutePath.settingsPages,
  group: RoutePath.settingsDirectory,
};

/** Project-scoped entities live under the project's settings. */
const PROJECT_SETTINGS_BY_ENTITY: Record<string, string> = {
  state: RoutePath.projectSettingsWorkflow,
  workflow_transition: RoutePath.projectSettingsWorkflow,
  issue_type: RoutePath.projectSettingsTypes,
  screen: RoutePath.projectSettingsScreens,
  release: RoutePath.projectSettingsReleases,
  form: RoutePath.projectSettingsForms,
  sla_policy: RoutePath.projectSettingsSla,
};

export function auditEntityLink(entry: AuditEntry): AuditLink | null {
  const refs = entry.refs ?? {};
  if (entry.entity_type === "item" && typeof refs.item?.key === "string") {
    return { to: RoutePath.issue, params: { itemKey: refs.item.key } };
  }
  if (entry.entity_type === "page") {
    // RADD-1233: the permalink — a ref written at event time may name a path
    // that has since moved, and the number (or id) never does.
    const page = refs.page;
    const key = typeof page?.number === "number" ? page.number : page?.id;
    if (typeof key === "number" || typeof key === "string") return pagePermalink(key);
    return null;
  }
  if (entry.entity_type === "project" && entry.project) {
    return { to: RoutePath.projectSettingsGeneral, params: { projectKey: entry.project.key } };
  }
  if (entry.entity_type === "scoped_setting") {
    return entry.project
      ? { to: RoutePath.projectSettingsGeneral, params: { projectKey: entry.project.key } }
      : { to: RoutePath.settingsGeneral };
  }
  const projectPage = PROJECT_SETTINGS_BY_ENTITY[entry.entity_type];
  if (projectPage && entry.project) {
    return { to: projectPage, params: { projectKey: entry.project.key } };
  }
  const settingsPage = SETTINGS_BY_ENTITY[entry.entity_type];
  return settingsPage ? { to: settingsPage } : null;
}

/** "Hussein · Role updated · Contributor" — the row's sentence, in three parts. */
export function auditSentence(entry: AuditEntry): { who: string; did: string; what: string } {
  return {
    who: entry.actor?.name ?? (entry.automated ? "An automation" : "System"),
    did: entry.event_label,
    what: entry.entity_label ?? entry.entity_id,
  };
}
