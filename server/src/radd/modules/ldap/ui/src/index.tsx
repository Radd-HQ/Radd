import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { DirectorySettingsPage } from "./DirectoryPage";

export default definePlugin({
  contributions: [
    { id: "settings", slot: SlotId.settingsPage, match: "/settings/directory", render: () => <DirectorySettingsPage /> },
  ],
});
