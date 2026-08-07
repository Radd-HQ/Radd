import { useCurrentUser } from "../../lib/hooks";
import { INSTANCE_HOMED_SECTIONS, InstanceRole, SettingScope } from "../../lib/types";
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
        // RADD-930: the REMAINDER — every key whose owner didn't claim a
        // surface that exists at instance scope. Directory keys land on the
        // Directory tab, AI toggles on AI, time policy on Time logging, all by
        // their own declaration; the release/CSAT/workflow defaults have tabs
        // only per PROJECT, so their instance-wide values belong here, which is
        // exactly what this page is for.
        <ScopedSettingsEditor
          scope={SettingScope.instance}
          homed={INSTANCE_HOMED_SECTIONS}
        />
      ) : (
        <p className="text-sm text-fg-muted">
          Changing the product defaults requires an instance admin.
        </p>
      )}
    </SettingsPage>
  );
}
