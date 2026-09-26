import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { AuditSettingsPage } from "./SettingsPage";
import { ChangeHistoryPanel } from "./ChangeHistoryPanel";
import { SettingsFooter } from "./SettingsFooter";
import type { ComponentProps } from "react";
export default definePlugin({contributions: [
  {id: "settings", slot: SlotId.settingsPage, match: "/settings/audit", render: () => <AuditSettingsPage />},
  {id: "history", slot: SlotId.entityHistory, render: props => <ChangeHistoryPanel {...(props as unknown as ComponentProps<typeof ChangeHistoryPanel>)} />},
  {id: "settings-footer", slot: SlotId.settingsFooter, render: props => <SettingsFooter {...(props as unknown as ComponentProps<typeof SettingsFooter>)} />},
]});
