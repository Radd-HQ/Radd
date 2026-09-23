import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { ApiError, errorMessage } from "../lib/api";
import { mfaEnrollmentConfirm, mfaEnrollmentSetup } from "../lib/auth";
import { Button } from "./Button";
import { Spinner } from "./Spinner";
import { RecoveryCodesOnce, TotpEnrolmentStep } from "./settings/TotpEnrolment";

/**
 * RADD-1279: the sign-in page's forced enrolment. The instance requires
 * two-factor, this account has none, and the refused login handed us a
 * ticket instead of a cookie. Setup and confirm go through the ticket; the
 * confirm sets the session cookie, then the recovery codes are shown once
 * before the person continues into the app.
 */
export function MfaEnrollment({
  ticket,
  onSignedIn,
  onRestart,
}: {
  ticket: string;
  onSignedIn: () => void;
  onRestart: () => void;
}) {
  const [codes, setCodes] = useState<string[] | null>(null);
  const setup = useMutation({ mutationFn: () => mfaEnrollmentSetup(ticket) });
  const confirm = useMutation({
    mutationFn: (code: string) => mfaEnrollmentConfirm(ticket, code),
    onSuccess: (result) => setCodes(result.recovery_codes),
  });

  // One setup per ticket: the effect fires once for the ticket this mounted with.
  const { mutate: startSetup } = setup;
  useEffect(() => startSetup(), [startSetup, ticket]);

  if (codes) return <RecoveryCodesOnce codes={codes} onDone={onSignedIn} />;

  // An expired ticket 401s on setup; a wrong code 401s on confirm.
  const expired = setup.error instanceof ApiError && setup.error.status === 401;
  if (setup.isError) {
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-subtle bg-surface/40 p-5">
        <p className="text-xs text-fg-secondary">
          {expired ? "That setup link has expired." : errorMessage(setup.error)}
        </p>
        <Button onClick={onRestart} className="justify-center">Sign in again</Button>
      </div>
    );
  }
  if (!setup.data) return <Spinner label="Preparing two-factor setup…" />;

  const confirmError =
    confirm.error instanceof ApiError && confirm.error.status === 401
      ? "That code didn't match — check the app's clock and try the next code."
      : confirm.error
        ? errorMessage(confirm.error)
        : undefined;

  return (
    <TotpEnrolmentStep
      setup={setup.data}
      confirming={confirm.isPending}
      error={confirmError}
      onConfirm={(code) => confirm.mutate(code)}
      confirmLabel="Confirm and sign in"
      intro={
        <p className="flex items-start gap-2 text-[13px] text-heading" data-mfa-enrollment>
          <ShieldAlert size={15} className="mt-0.5 shrink-0 text-accent-text" aria-hidden />
          This server requires two-factor authentication. Set it up now to finish signing in.
        </p>
      }
    />
  );
}
