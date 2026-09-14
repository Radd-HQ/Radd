import { Lock } from "lucide-react";
import { useCurrentUser } from "../../lib/hooks";
import { InstanceRole } from "../../lib/types";
import { EmptyState } from "../../components/EmptyState";
import { AiFeaturesSection } from "../../components/settings/AiFeaturesSection";
import { AiPresetsSection } from "../../components/settings/AiPresetsSection";
import { AiProvidersSection } from "../../components/settings/AiProvidersSection";
import { AiRolesSection } from "../../components/settings/AiRolesSection";
import { SettingsPage } from "../../components/settings/SettingsPage";

/**
 * Settings → AI (spec 101) — instance admins only (the API 403s otherwise).
 * Providers (endpoints + keys) → roles (what each model is for) → feature
 * toggles → the editor preset-prompt library.
 */
export function AiSettingsPage() {
  const me = useCurrentUser();
  const isInstanceAdmin = me?.instance_role === InstanceRole.admin;

  return (
    <SettingsPage history={{ entities: ["ai_provider", "ai_role", "ai_preset", "scoped_setting"] }}
      title="AI"
      description="Model providers, what each model is used for, which AI features are on, and the editor prompt library. A feature runs when its toggle is on and its role has a provider."
    >
      {!isInstanceAdmin ? (
        <EmptyState icon={Lock} message="Only instance admins can manage AI settings." />
      ) : (
        <div className="flex flex-col gap-8">
          <AiProvidersSection />
          <AiRolesSection />
          <AiFeaturesSection />
          <AiPresetsSection />
        </div>
      )}
    </SettingsPage>
  );
}
