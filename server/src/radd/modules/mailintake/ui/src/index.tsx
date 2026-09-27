import { definePlugin, SlotId, type AutomationNodeInspectorProps, type Item, type Project } from "@radd/plugin-sdk";
import { MailHealthCard } from "./MailHealthCard";
import { ExternalRequesterChip } from "./ExternalRequesterChip";
import { SendEmailInspector } from "./SendEmailInspector";
import { EmailSettingsPage } from "./SettingsPage";
import { signedBody } from "./SignedBody";
import { SEND_EMAIL_NODE } from "./types";

/** mailintake: Settings → Email, the Monitoring mail card, the external-requester chip, mailed bodies'
 *  folded signatures, and the form of its Send email automation action. */
export default definePlugin({
  contributions: [
    {
      id: "send-email-inspector",
      slot: SlotId.automationNodeInspector,
      match: SEND_EMAIL_NODE,
      // The node's form, not a feature to switch off: without it the node is edited from its schema.
      toggleable: false,
      render: (props) => <SendEmailInspector {...(props as unknown as AutomationNodeInspectorProps)} />,
    },
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
