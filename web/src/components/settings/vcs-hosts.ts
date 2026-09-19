import { useQuery } from "@tanstack/react-query";
import {
  ApiPath,
  apiForgejoBackfillPath,
  apiForgejoConnectionPath,
  apiForgejoConnectionTestPath,
  apiForgejoRepoPath,
  apiGithubBackfillPath,
  apiGithubConnectionPath,
  apiGithubConnectionTestPath,
  apiGithubRepoPath,
  apiGitlabBackfillPath,
  apiGitlabConnectionPath,
  apiGitlabConnectionTestPath,
  apiGitlabRepoPath,
} from "../../lib/constants";
import { Entity } from "../../lib/cache";
import {
  forgejoConnectionsQuery,
  forgejoReposQuery,
  githubConnectionsQuery,
  githubReposQuery,
  gitlabConnectionsQuery,
  gitlabReposQuery,
} from "../../lib/queries";
import { VcsProvider } from "../../lib/types";
import type { VcsHostConfig } from "./VcsHostSettings";

/**
 * The three host kinds Settings → Version control offers as tabs (RADD-1262).
 * Each is a `VcsHostConfig` over the same wire shape; `plugin` is the module
 * that serves it, so a disabled kind explains itself instead of 404ing.
 */
export const VcsHostKind = {
  forgejo: "forgejo",
  github: "github",
  gitlab: "gitlab",
} as const;
export type VcsHostKindValue = (typeof VcsHostKind)[keyof typeof VcsHostKind];

export const VCS_HOST_KINDS: readonly VcsHostKindValue[] = [
  VcsHostKind.forgejo,
  VcsHostKind.github,
  VcsHostKind.gitlab,
];

export function isVcsHostKind(value: unknown): value is VcsHostKindValue {
  return typeof value === "string" && (VCS_HOST_KINDS as readonly string[]).includes(value);
}

/** Forgejo/Gitea hosts and repositories (spec 111). */
const FORGEJO: VcsHostConfig = {
  provider: VcsProvider.forgejo,
  title: "Forgejo",
  historyEntities: ["forgejo_connection", "forgejo_repo", "vcs_user_link"],
  description:
    "Hosts whose pushes, branches and pull requests link themselves to issues by key. Map a repository to a project so its published releases create versions there. Time tracked on a pull request is mirrored into the linked issue, dated by when it was added.",
  webhookPath: "/api/v1/integrations/forgejo",
  namePlaceholder: "Forgejo",
  baseUrlPlaceholder: "https://git.example.com",
  secretHint: "The shared secret the host signs payloads with.",
  tokenHint: "Read-only. Needed for backfill, the connection test and tracked-time mirroring.",
  useConnections: () => useQuery(forgejoConnectionsQuery()),
  useRepos: () => useQuery(forgejoReposQuery()),
  entities: [Entity.forgejoConnection, Entity.forgejoRepo],
  paths: {
    connections: ApiPath.forgejoConnections,
    repos: ApiPath.forgejoRepos,
    connection: apiForgejoConnectionPath,
    connectionTest: apiForgejoConnectionTestPath,
    repo: apiForgejoRepoPath,
    backfill: apiForgejoBackfillPath,
  },
};

/** GitHub hosts and repositories (RADD-1129). */
const GITHUB: VcsHostConfig = {
  provider: VcsProvider.github,
  title: "GitHub",
  historyEntities: ["github_connection", "github_repo", "vcs_user_link"],
  description:
    "Repositories whose pushes, branches, pull requests and check runs link themselves to issues by key. Map a repository to a project so its published releases create versions there and ship the work waiting for them. GitHub has no time tracking, so a pull-request comment carries it: “/spend 1h30”, “/spend 45m 2026-09-18 note”, “/spend 1h KEY-12” to log to another issue, “/unspend” to forget yours on that PR — mirrored into the linked issue by the mapped account.",
  webhookPath:
    "/api/v1/integrations/github (content type application/json, events: push, pull requests, releases, check suites, workflow runs)",
  namePlaceholder: "GitHub",
  baseUrlPlaceholder: "https://github.com",
  defaultBaseUrl: "https://github.com",
  secretHint: "The secret entered on the webhook; GitHub signs every delivery with it (X-Hub-Signature-256).",
  tokenHint:
    "Read-only. A fine-grained token with Contents and Pull requests read access; needed for backfill and the connection test.",
  useConnections: () => useQuery(githubConnectionsQuery()),
  useRepos: () => useQuery(githubReposQuery()),
  entities: [Entity.githubConnection, Entity.githubRepo],
  paths: {
    connections: ApiPath.githubConnections,
    repos: ApiPath.githubRepos,
    connection: apiGithubConnectionPath,
    connectionTest: apiGithubConnectionTestPath,
    repo: apiGithubRepoPath,
    backfill: apiGithubBackfillPath,
  },
};

/** GitLab hosts and projects (RADD-1253). */
const GITLAB: VcsHostConfig = {
  provider: VcsProvider.gitlab,
  title: "GitLab",
  historyEntities: ["gitlab_connection", "gitlab_repo", "vcs_user_link"],
  description:
    "Hosts whose pushes, branches and merge requests link themselves to issues by key (the key in a branch name, a commit message or a merge request title). Time logged on a merge request with /spend is mirrored into the linked issue's worklogs, and the backfill imports history — including its time — once.",
  webhookPath:
    "/api/v1/integrations/gitlab (project or group hook; triggers: push, merge request; paste the same secret token here)",
  namePlaceholder: "GitLab",
  baseUrlPlaceholder: "https://gitlab.example.com",
  defaultBaseUrl: "https://gitlab.com",
  secretHint: "The hook's Secret token; GitLab sends it back on every delivery (X-Gitlab-Token).",
  tokenHint:
    "A read_api token. Needed for backfill, the connection test and time mirroring; an administrator's token also matches authors by email automatically.",
  useConnections: () => useQuery(gitlabConnectionsQuery()),
  useRepos: () => useQuery(gitlabReposQuery()),
  entities: [Entity.gitlabConnection, Entity.gitlabRepo],
  paths: {
    connections: ApiPath.gitlabConnections,
    repos: ApiPath.gitlabRepos,
    connection: apiGitlabConnectionPath,
    connectionTest: apiGitlabConnectionTestPath,
    repo: apiGitlabRepoPath,
    backfill: apiGitlabBackfillPath,
  },
};

export const VCS_HOST_CONFIGS: Record<VcsHostKindValue, VcsHostConfig> = {
  forgejo: FORGEJO,
  github: GITHUB,
  gitlab: GITLAB,
};
