import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { MonitoringSettingsPage } from "./SettingsPage";

export default definePlugin({
  contributions: [{ id: "settings", slot: SlotId.settingsPage, match: "/settings/monitoring", render: () => <MonitoringSettingsPage /> }],
});
