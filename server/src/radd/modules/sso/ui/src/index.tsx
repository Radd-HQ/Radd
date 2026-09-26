import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { ProvidersPanel } from "./ProvidersPanel";

/** The sso plugin's UI remote (RADD-1380): the provider registry, as a section of the host's
 *  Settings → Sign-in page. The page is the host's because it also carries the instance MFA
 *  policy, which the core `auth` module declares — so disabling sso withdraws the providers and
 *  leaves the two-factor switch where admins find it. */
export default definePlugin({
  contributions: [
    { id: "providers", slot: SlotId.settingsSection, match: "sign-in", label: "Sign-in providers", render: () => <ProvidersPanel /> },
  ],
});
