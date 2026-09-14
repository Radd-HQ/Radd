import {
  ApiPath,
  apiForgejoBackfillPath,
  apiForgejoConnectionPath,
  apiForgejoConnectionTestPath,
  apiForgejoRepoPath,
} from "../../lib/constants";
import { Entity } from "../../lib/cache";
import { forgejoConnectionsQuery, forgejoReposQuery } from "../../lib/queries";
import { useQuery } from "@tanstack/react-query";
import { VcsHostSettings, type VcsHostConfig } from "../../components/settings/VcsHostSettings";

/** Forgejo/Gitea hosts and repositories (spec 111). */
const FORGEJO: VcsHostConfig = {
  title: "Forgejo",
  historyEntities: ["forgejo_connection", "forgejo_repo"],
  description:
    "Hosts whose pushes, branches and pull requests link themselves to issues by key. Map a repository to a project so its published releases create versions there.",
  webhookPath: "/api/v1/integrations/forgejo",
  namePlaceholder: "Forgejo",
  baseUrlPlaceholder: "https://git.example.com",
  secretHint: "The shared secret the host signs payloads with.",
  tokenHint: "Read-only. Needed for backfill and the connection test.",
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

export function ForgejoSettingsPage() {
  return <VcsHostSettings config={FORGEJO} />;
}
