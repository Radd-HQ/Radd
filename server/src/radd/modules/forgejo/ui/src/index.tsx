import { definePlugin, Slot } from "@radd/plugin-sdk";
import { VCS_PROVIDER_SETTINGS_SLOT, VCS_HOST_SETTINGS_SLOT, type VcsHostConfig } from "@radd-plugin-ui/vcs/host-contract";

/** This connector's tab on Settings → Version control: its wording; VCS renders the rest. */
const config: VcsHostConfig = {
  provider: "forgejo",
  title: "Forgejo",
  description:
    "Hosts whose pushes, branches and pull requests link themselves to issues by key. Map a repository to a project to make it the project its release triggers name. For a repository with “Mirror time” switched on, time tracked on a pull request is copied into the linked issue, dated by when it was added.",
  webhookPath: "/api/v1/integrations/forgejo",
  namePlaceholder: "Forgejo",
  baseUrlPlaceholder: "https://git.example.com",
  secretHint: "The shared secret the host signs payloads with.",
  tokenHint: "Read-only. Needed for backfill, the connection test and tracked-time mirroring.",
  changeNoun: "pull request",
};

export default definePlugin({contributions: [
  {id: "settings", order: 10, slot: VCS_PROVIDER_SETTINGS_SLOT, match: config.provider, title: config.title,
    render: () => <Slot id={VCS_HOST_SETTINGS_SLOT} config={config} fallback={<p className="text-sm text-fg-muted">Version control settings are unavailable.</p>} />},
]});
