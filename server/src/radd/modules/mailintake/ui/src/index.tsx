import { definePlugin, SlotId, type Item, type Project } from "@radd/plugin-sdk";
import { MailHealthCard } from "./MailHealthCard";
import { ExternalRequesterChip } from "./ExternalRequesterChip";
import { EmailSettingsPage } from "./SettingsPage";

/**
 * The `mailintake` plugin's UI remote entry (spec 94). The host loader imports this bundle and
 * calls `activate(ctx)`; `ctx.registerSlot` is pre-bound to this plugin's name so a disable removes
 * exactly this contribution. Contributes Settings → Email (RADD-1378; its nav entry is declared on
 * the backend manifest, so disabling the plugin withdraws both), the outbound-mail card on
 * Monitoring, and the external-requester chip in the issue right-rail.
 */
export default definePlugin({
  contributions: [
    { id: "settings", slot: SlotId.settingsPage, match: "/settings/email", render: () => <EmailSettingsPage /> },
    { id: "mail-health", slot: SlotId.settingsSection, match: "monitoring", order: 10, render: () => <MailHealthCard /> },
  ],
  activate(ctx) {
    ctx.registerSlot(SlotId.issuePanelSection, {
      id: "mailintake",
      order: 10,
      render: (props) => {
        const { item } = props as { item: Item; project: Project };
        return <ExternalRequesterChip itemId={item.id} />;
      },
    });
  },
});
