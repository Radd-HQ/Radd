import { useCurrentUser } from "../../lib/hooks";
import {
  AI_FEATURE_SETTING_KEYS,
  DIRECTORY_SETTING_KEYS,
  InstanceRole,
  SettingScope,
} from "../../lib/types";
import { ScopedSettingsEditor } from "../../components/settings/ScopedSettingsEditor";
import { SettingsPage } from "../../components/settings/SettingsPage";

/**
 * Product defaults (spec 67 two-scope cascade) — the INSTANCE-scope editor.
 * Each value here is the default for every project; a project overrides it
 * under its own settings (Project settings → General). Writes are
 * instance-scope, so the page (and its nav entry) is instance-admin only.
 */
export function GeneralSettingsPage() {
  const user = useCurrentUser();
  const isAdmin = user?.instance_role === InstanceRole.admin;

  return (
    <SettingsPage
      title="General"
      description="Defaults for every project — each project can override these under its own settings."
    >
      {isAdmin ? (
        // Directory keys (spec 85) live on the Directory tab; AI feature
        // toggles (spec 101) on the AI tab — same registry, no duplication.
        <ScopedSettingsEditor
          scope={SettingScope.instance}
          filter={(row) =>
            !DIRECTORY_SETTING_KEYS.includes(row.key) &&
            !AI_FEATURE_SETTING_KEYS.includes(row.key)
          }
        />
      ) : (
        <p className="text-sm text-fg-muted">
          Changing the product defaults requires an instance admin.
        </p>
      )}
    </SettingsPage>
  );
}
