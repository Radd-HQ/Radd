import { useQuery } from "@tanstack/react-query";
import { aiRolesQuery } from "../../lib/queries";
import {
  AI_FEATURE_SETTING_KEYS,
  AiRole,
  SettingScope,
  type AiRoleValue,
} from "../../lib/types";
import { ScopedSettingsEditor } from "./ScopedSettingsEditor";

const sectionHeadClasses = "mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted";

/** Which features each role carries — mirrors the backend FEATURE_ROLE map. */
const ROLE_FEATURES: readonly { role: AiRoleValue; label: string; features: string }[] = [
  {
    role: AiRole.chat,
    label: "chat",
    features: "editor AI actions, issue summarize, natural language → SLQ, similar-issues rerank",
  },
  { role: AiRole.embeddings, label: "embeddings", features: "semantic search" },
  { role: AiRole.vision, label: "vision", features: "LLM storage routing" },
];

/**
 * The six instance-scope feature toggles (spec 101) — the same scoped-settings
 * registry as General, filtered to the AI keys. A feature is live only when its
 * toggle is on AND its role resolves, so unassigned roles get a hint line here
 * (per-toggle disabling doesn't fit ScopedSettingsEditor's API — don't fork it).
 */
export function AiFeaturesSection() {
  const roles = useQuery(aiRolesQuery());
  const assigned = new Set((roles.data ?? []).map((row) => row.role));
  const missing = roles.isSuccess
    ? ROLE_FEATURES.filter((entry) => !assigned.has(entry.role))
    : [];

  return (
    <section>
      <h2 className={sectionHeadClasses}>Features</h2>
      <p className="mb-3 text-xs text-fg-muted">
        Instance-wide switches. A toggle only takes effect once the role its feature needs is
        assigned above.
      </p>
      <ScopedSettingsEditor
        scope={SettingScope.instance}
        filter={(row) => AI_FEATURE_SETTING_KEYS.includes(row.key)}
      />
      {missing.map((entry) => (
        <p key={entry.role} className="mt-2 text-xs text-amber-400/90">
          The {entry.label} role is unassigned — {entry.features} won't activate even when
          toggled on.
        </p>
      ))}
    </section>
  );
}
