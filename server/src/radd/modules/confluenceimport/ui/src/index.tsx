import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { ConfluenceImportPage } from "./SettingsPage";

/** The Confluence importer's UI remote (RADD-1382): its settings page. The nav
 * entry (Settings → Import → Confluence) is declared on the backend manifest, so
 * disabling the plugin withdraws both. */
export default definePlugin({
  contributions: [
    { id: "settings", slot: SlotId.settingsPage, match: "/settings/confluence-import", render: () => <ConfluenceImportPage /> },
  ],
});
