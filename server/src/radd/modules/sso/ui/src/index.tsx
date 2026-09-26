import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { ProvidersPanel } from "./ProvidersPanel";

/** sso: providers as a section of the host's Sign-in page (the page also carries auth's MFA policy, so it stays when sso is off). */
export default definePlugin({
  contributions: [
    { id: "providers", slot: SlotId.settingsSection, match: "sign-in", label: "Sign-in providers", render: () => <ProvidersPanel /> },
  ],
});
