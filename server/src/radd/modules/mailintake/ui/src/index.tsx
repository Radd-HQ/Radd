import { definePlugin, SlotId, type Item, type Project } from "@radd/plugin-sdk";
import { MailHealthCard } from "./MailHealthCard";
import { ExternalRequesterChip } from "./ExternalRequesterChip";
import { EmailSettingsPage } from "./SettingsPage";
import { signedBody } from "./SignedBody";

/** mailintake: Settings → Email, the Monitoring mail card, the external-requester chip, and mailed bodies' folded signatures. */
export default definePlugin({
  contributions: [
    { id: "settings", slot: SlotId.settingsPage, match: "/settings/email", render: () => <EmailSettingsPage /> },
    { id: "mail-health", slot: SlotId.settingsSection, match: "monitoring", order: 10, render: () => <MailHealthCard /> },
    signedBody,
    {
      id: "mailintake",
      slot: SlotId.issuePanelSection,
      order: 10,
      render: (props) => <ExternalRequesterChip itemId={(props as { item: Item; project: Project }).item.id} />,
    },
  ],
});
