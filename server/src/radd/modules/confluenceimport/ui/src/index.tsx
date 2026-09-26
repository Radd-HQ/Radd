import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { ConfluenceImportPage } from "./SettingsPage";

/** The Confluence importer's settings page; its nav entry is declared on the backend manifest. */
export default definePlugin({
  contributions: [
    { id: "settings", slot: SlotId.settingsPage, match: "/settings/confluence-import", render: () => <ConfluenceImportPage /> },
  ],
});
