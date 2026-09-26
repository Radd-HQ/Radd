export const VCS_PROVIDER_SETTINGS_SLOT = "vcs.provider-settings";
export const VCS_HOST_SETTINGS_SLOT = "vcs.host-settings";

/**
 * What a connector (gitlab, github, forgejo) tells the shared Version control
 * page about itself: its provider key and its wording. Everything that is
 * mechanical — REST paths, cache tags, audited entity types — follows from the
 * provider key by one convention VCS owns (`hostPaths`), so a connector cannot
 * restate it wrong.
 */
export type VcsHostConfig = {
  /** The VcsProvider this host kind writes links as — also the connector's route prefix. */
  provider: string;
  title: string;
  description: string;
  /** Where to register the webhook on the host, shown in the empty state. */
  webhookPath: string;
  namePlaceholder: string;
  baseUrlPlaceholder: string;
  /** When set, the base URL field is optional and defaults to this host. */
  defaultBaseUrl?: string;
  tokenHint: string;
  secretHint: string;
  /** What a merged change is called on this host ("merge request", "pull request"). */
  changeNoun: string;
};
