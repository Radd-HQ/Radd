import { definePlugin, Slot } from "@radd/plugin-sdk";
import { VCS_PROVIDER_SETTINGS_SLOT, VCS_HOST_SETTINGS_SLOT, type VcsHostConfig } from "@radd-plugin-ui/vcs/host-contract";

/** This connector's tab on Settings → Version control: its wording; VCS renders the rest. */
const config: VcsHostConfig = {
  provider: "gitlab",
  title: "GitLab",
  description:
    "Hosts whose pushes, branches and merge requests link themselves to issues by key (the key in a branch name, a commit message or a merge request title). For a repository with “Mirror time” switched on, time logged on a merge request with /spend is copied into the linked issue's worklogs, and the backfill imports that history once.",
  webhookPath:
    "/api/v1/integrations/gitlab (project or group hook; triggers: push, merge request, pipeline, deployment, releases; paste the same secret token here)",
  namePlaceholder: "GitLab",
  baseUrlPlaceholder: "https://gitlab.example.com",
  defaultBaseUrl: "https://gitlab.com",
  secretHint: "The hook's Secret token; GitLab sends it back on every delivery (X-Gitlab-Token).",
  tokenHint:
    "A read_api token. Needed for backfill, the connection test and time mirroring; an administrator's token also matches authors by email automatically.",
  changeNoun: "merge request",
};

export default definePlugin({contributions: [
  {id: "settings", order: 30, slot: VCS_PROVIDER_SETTINGS_SLOT, match: config.provider, title: config.title,
    render: () => <Slot id={VCS_HOST_SETTINGS_SLOT} config={config} fallback={<p className="text-sm text-fg-muted">Version control settings are unavailable.</p>} />},
]});
