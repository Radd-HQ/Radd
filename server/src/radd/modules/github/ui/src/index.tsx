import { definePlugin, Slot } from "@radd/plugin-sdk";
import { VCS_PROVIDER_SETTINGS_SLOT, VCS_HOST_SETTINGS_SLOT, type VcsHostConfig } from "@radd-plugin-ui/vcs/host-contract";

/** This connector's tab on Settings → Version control: its wording; VCS renders the rest. */
const config: VcsHostConfig = {
  provider: "github",
  title: "GitHub",
  description:
    "Repositories whose pushes, branches, pull requests and check runs link themselves to issues by key. Map a repository to a project to make it the project its release triggers name. GitHub has no time tracking, so a pull-request comment carries it: “/spend 1h30”, “/spend 45m 2026-09-18 note”, “/spend 1h KEY-12” to log to another issue, “/unspend” to forget yours on that PR — copied into the linked issue by the mapped account, for a repository with “Mirror time” switched on.",
  webhookPath:
    "/api/v1/integrations/github (content type application/json, events: push, pull requests, releases, check suites, workflow runs)",
  namePlaceholder: "GitHub",
  baseUrlPlaceholder: "https://github.com",
  defaultBaseUrl: "https://github.com",
  secretHint: "The secret entered on the webhook; GitHub signs every delivery with it (X-Hub-Signature-256).",
  tokenHint:
    "Read-only. A fine-grained token with Contents and Pull requests read access; needed for backfill and the connection test.",
  changeNoun: "pull request",
};

export default definePlugin({contributions: [
  {id: "settings", order: 20, slot: VCS_PROVIDER_SETTINGS_SLOT, match: config.provider, title: config.title,
    render: () => <Slot id={VCS_HOST_SETTINGS_SLOT} config={config} fallback={<p className="text-sm text-fg-muted">Version control settings are unavailable.</p>} />},
]});
