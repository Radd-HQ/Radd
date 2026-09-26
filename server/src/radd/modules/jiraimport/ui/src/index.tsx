import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { JiraImportPage } from "./ImportPage";

/** The jiraimport plugin's UI remote (RADD-1382): its settings page. The nav
 * entry (Settings → Import → Jira) is declared on the backend manifest, so
 * disabling the plugin withdraws both. */
export default definePlugin({
  contributions: [
    { id: "settings", slot: SlotId.settingsPage, match: "/settings/jira-import", render: () => <JiraImportPage /> },
  ],
});
