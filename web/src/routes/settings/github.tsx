import {
  ApiPath,
  apiGithubBackfillPath,
  apiGithubConnectionPath,
  apiGithubConnectionTestPath,
  apiGithubRepoPath,
} from "../../lib/constants";
import { Entity } from "../../lib/cache";
import { githubConnectionsQuery, githubReposQuery } from "../../lib/queries";
import { useQuery } from "@tanstack/react-query";
import { VcsHostSettings, type VcsHostConfig } from "../../components/settings/VcsHostSettings";

/** GitHub hosts and repositories (RADD-1129). */
const GITHUB: VcsHostConfig = {
  title: "GitHub",
  description:
    "Repositories whose pushes, branches, pull requests and check runs link themselves to issues by key. Map a repository to a project so its published releases create versions there and ship the work waiting for them.",
  webhookPath: "/api/v1/integrations/github (content type application/json, events: push, pull requests, releases, check suites, workflow runs)",
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

export function GithubSettingsPage() {
  return <VcsHostSettings config={GITHUB} />;
}
