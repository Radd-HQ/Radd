import { SettingScope } from "../../lib/types";
import { useIsInstanceAdmin } from "@radd/plugin-sdk";
import { ScopedSettingsEditor } from "../../components/settings/ScopedSettingsEditor";
import { SettingsPage } from "../../components/settings/SettingsPage";

/**
 * Product defaults (spec 67 two-scope cascade) — the INSTANCE-scope editor.
 * Each value here is the default for every project; a project overrides it
 * under its own settings (Project settings → General). Writes are
 * instance-scope, so the page (and its nav entry) is instance-admin only.
 */
export function GeneralSettingsPage() {
  const isAdmin = useIsInstanceAdmin();

  return (
    <SettingsPage history={{ entities: ["scoped_setting"] }}
      title="General"
      description="Defaults for every project — each project can override these under its own settings."
    >
      {isAdmin ? (
        // RADD-930: the REMAINDER — every key whose owner claimed no instance-scope surface (keys
        // whose tabs exist only per project land here too).
        <ScopedSettingsEditor
          scope={SettingScope.instance}
          general
        />
      ) : (
        <p className="text-sm text-fg-muted">
          Changing the product defaults requires an instance admin.
        </p>
      )}
    </SettingsPage>
  );
}
