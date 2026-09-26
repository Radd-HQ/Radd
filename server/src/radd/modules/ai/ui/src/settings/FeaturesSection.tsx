import { ScopedSettings } from "@radd/plugin-sdk";
import { useAiRoles } from "./queries";
import { AiRole, sectionHeadClasses, type AiRoleValue } from "./types";

/** Which features each role carries — mirrors the backend FEATURE_ROLE map. */
const ROLE_FEATURES: readonly { role: AiRoleValue; label: string; features: string }[] = [
  {
    role: AiRole.chat,
    label: "chat",
    features: "editor AI actions, issue summarize, natural language → SLQ, similar-issues rerank, LLM mail routing",
  },
  { role: AiRole.embeddings, label: "embeddings", features: "semantic search" },
  { role: AiRole.vision, label: "vision", features: "LLM storage routing" },
];

/**
 * The instance-scope feature toggles (spec 101): the settings-cascade editor over the `ai` section
 * this plugin declares. The rows come from its backend `SettingSpec`s, so a new toggle appears by
 * being registered; only the role→features prose is a hand-kept mirror of `features.FEATURE_ROLE`.
 * A feature is live only when its toggle is on AND its role resolves, so unassigned roles get a
 * hint line here.
 */
export function FeaturesSection() {
  const roles = useAiRoles();
  const assigned = new Set((roles.data ?? []).map((row) => row.role));
  const missing = roles.isSuccess ? ROLE_FEATURES.filter((entry) => !assigned.has(entry.role)) : [];

  return (
    <section data-ai-features>
      <h2 className={sectionHeadClasses}>Features</h2>
      <p className="mb-3 text-xs text-fg-muted">
        Instance-wide switches. A toggle only takes effect once the role its feature needs is assigned above.
      </p>
      <ScopedSettings scope="instance" section="ai" />
      {missing.map((entry) => (
        <p key={entry.role} className="mt-2 text-xs text-status-warning-ink">
          The {entry.label} role is unassigned — {entry.features} won't activate even when toggled on.
        </p>
      ))}
    </section>
  );
}
