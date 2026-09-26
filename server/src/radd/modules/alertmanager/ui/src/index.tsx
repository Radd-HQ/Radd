import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { AlertmanagerSettingsPage } from "./SettingsPage";

export default definePlugin({
  contributions: [
    { id: "settings", slot: SlotId.settingsPage, match: "/settings/alertmanager", render: () => <AlertmanagerSettingsPage /> },
  ],
});
