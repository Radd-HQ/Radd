import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { DirectorySettingsPage } from "./DirectoryPage";

/** The ldap plugin's UI remote (RADD-1381): Settings → Directory. The nav entry is declared on
 * the backend manifest, so disabling the plugin withdraws both. */
export default definePlugin({
  contributions: [
    { id: "settings", slot: SlotId.settingsPage, match: "/settings/directory", render: () => <DirectorySettingsPage /> },
  ],
});
