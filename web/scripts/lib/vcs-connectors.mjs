/** What `GET /vcs/connectors` answers for the connector plugins a proof has enabled (RADD-1435):
 *  the wording each connector's manifest declares, in the server's tab order. */
const WORDING = {
  forgejo: { title: "Forgejo", change_noun: "pull request", default_base_url: "", base_url_placeholder: "https://git.example.com" },
  github: { title: "GitHub", change_noun: "pull request", default_base_url: "https://github.com", base_url_placeholder: "https://github.com" },
  gitlab: { title: "GitLab", change_noun: "merge request", default_base_url: "https://gitlab.com", base_url_placeholder: "https://gitlab.example.com" },
};

/** `enabled`: every enabled plugin's name (the capabilities' `plugins`); non-connectors are ignored. */
export function vcsConnectors(enabled) {
  return Object.entries(WORDING).filter(([provider]) => [...enabled].includes(provider)).map(([provider, wording]) => ({
    provider,
    description: `${wording.title} hosts whose pushes link themselves to issues by key.`,
    webhook_path: `/api/v1/integrations/${provider}`,
    name_placeholder: wording.title,
    token_hint: "Read-only.",
    secret_hint: "The shared secret.",
    ...wording,
  }));
}
