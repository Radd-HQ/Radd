import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { AlertmanagerSettingsPage } from "./SettingsPage";

/** The alertmanager plugin's UI remote (RADD-1370): its settings page. The nav
 * entry is declared on the backend manifest, so disabling the plugin withdraws
 * both. */
export default definePlugin({
  contributions: [
    { id: "settings", slot: SlotId.settingsPage, match: "/settings/alertmanager", render: () => <AlertmanagerSettingsPage /> },
  ],
});
