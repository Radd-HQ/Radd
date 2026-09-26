import { Lock } from "lucide-react";
import { EmptyState, SettingsPage, Spinner, useCurrentUser, useIsInstanceAdmin } from "@radd/plugin-sdk";
import { FeaturesSection } from "./FeaturesSection";
import { PresetsSection } from "./PresetsSection";
import { ProvidersSection } from "./ProvidersSection";
import { RolesSection } from "./RolesSection";

/**
 * Settings → AI (spec 101; the ai plugin's own page since RADD-1379) — instance admins only (the
 * API 403s otherwise). Providers (endpoints + keys) → roles (what each model is for) → feature
 * toggles → the editor preset-prompt library.
 */
export function AiSettingsPage() {
  const me = useCurrentUser();
  const isAdmin = useIsInstanceAdmin();

  return (
    <SettingsPage history={{ entities: ["ai_provider", "ai_role", "ai_preset", "scoped_setting"] }}
      title="AI"
      description="Model providers, what each model is used for, which AI features are on, and the editor prompt library. A feature runs when its toggle is on and its role has a provider.">
      {!me ? (
        <Spinner label="Loading…" />
      ) : !isAdmin ? (
        <EmptyState icon={Lock} message="Only instance admins can manage AI settings." />
      ) : (
        <div className="flex flex-col gap-8">
          <ProvidersSection />
          <RolesSection />
          <FeaturesSection />
          <PresetsSection />
        </div>
      )}
    </SettingsPage>
  );
}
