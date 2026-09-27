import { Lock } from "lucide-react";
import { SettingScope } from "../../lib/types";
import { SettingsSection } from "../../lib/constants";
import { EmptyState, Slot, SlotId, useIsInstanceAdmin } from "@radd/plugin-sdk";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { ScopedSettingsEditor } from "../../components/settings/ScopedSettingsEditor";

/**
 * Settings → Sign-in (spec 110) — instance admins only (the API 403s otherwise).
 *
 * How people get in. The page is the host's because what it always carries —
 * the instance MFA policy — is the core `auth` module's; the ways IN are
 * contributed by the plugins that provide them, as sections keyed by this
 * page's segment (RADD-1380: sso's provider registry is one). Disabling such a
 * plugin withdraws its section and leaves the page.
 */
export function SignInSettingsPage() {
  const isInstanceAdmin = useIsInstanceAdmin();

  return (
    <SettingsPage history={{ entities: ["scoped_setting"] }}
      title="Sign-in"
      description="How people sign in to this server, and what a password sign-in must also prove."
      info={
        <>
          Sign-in methods that come from a plugin — single sign-on providers, for one — add
          their settings to this page while the plugin is enabled. The two-factor policy below
          always applies to <strong>password</strong> sign-ins.
        </>
      }
    >
      {!isInstanceAdmin ? (
        <EmptyState icon={Lock} message="Only instance admins can manage sign-in." />
      ) : (
        <div className="flex flex-col gap-8">
          <Slot id={SlotId.settingsSection} match={SettingsSection.signIn} />
          {/* RADD-1279: the instance MFA policy. Covers Radd PASSWORD sign-ins
              only — the setting's own description says so, and turning it on
              is refused while you are not enrolled yourself. */}
          <section data-mfa-policy>
            <h2 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted">
              Two-factor authentication
            </h2>
            <ScopedSettingsEditor scope={SettingScope.instance} section="signin.mfa" />
          </section>
        </div>
      )}
    </SettingsPage>
  );
}
