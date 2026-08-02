import { Lock } from "lucide-react";
import { useCurrentUser } from "../../lib/hooks";
import { InstanceRole } from "../../lib/types";
import { EmptyState } from "../../components/EmptyState";
import { ProvidersPanel } from "../../components/settings/signin/ProvidersPanel";
import { SettingsPage } from "../../components/settings/SettingsPage";

/**
 * Settings → Sign-in (spec 110) — instance admins only (the API 403s otherwise).
 * The identity providers the login page offers, and who each one may let in.
 */
export function SignInSettingsPage() {
  const me = useCurrentUser();
  const isInstanceAdmin = me?.instance_role === InstanceRole.admin;

  return (
    <SettingsPage
      title="Sign-in"
      description="The identity providers people can sign in with, and which email domains may create an account."
      info={
        <>
          A provider&rsquo;s domain list gates <strong>new accounts only</strong> — someone who
          already has a Radd account signs in from any domain. When a sign-in matches an
          existing account by verified email, it <strong>joins that account</strong> rather
          than creating a second one, so the same person keeps one identity whether they
          arrive through Active Directory, a password, or Google.
        </>
      }
    >
      {!isInstanceAdmin ? (
        <EmptyState icon={Lock} message="Only instance admins can manage sign-in." />
      ) : (
        <ProvidersPanel />
      )}
    </SettingsPage>
  );
}
