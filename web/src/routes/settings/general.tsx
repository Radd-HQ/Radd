import { useCurrentUser } from "../../lib/hooks";
import { InstanceRole, SettingScope } from "../../lib/types";
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
