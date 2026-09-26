import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { JiraImportPage } from "./ImportPage";

/** The Jira importer's settings page; its nav entry is declared on the backend manifest. */
export default definePlugin({
  contributions: [
    { id: "settings", slot: SlotId.settingsPage, match: "/settings/jira-import", render: () => <JiraImportPage /> },
  ],
});
