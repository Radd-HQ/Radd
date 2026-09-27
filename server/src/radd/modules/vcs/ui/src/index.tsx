import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { VcsSettingsPage } from "./SettingsPage";

export default definePlugin({ contributions: [
  { id: "settings", slot: SlotId.settingsPage, match: "/settings/vcs", render: () => <VcsSettingsPage /> },
] });
