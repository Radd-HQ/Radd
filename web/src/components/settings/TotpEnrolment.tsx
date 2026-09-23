import { useState, type FormEvent, type ReactNode } from "react";
import { Check, Copy, ShieldCheck } from "lucide-react";
import type { TotpSetup } from "../../lib/types";
import { Button } from "../Button";
import { TextField } from "../TextField";
import { CopyValue } from "./CopyValue";
import { TotpQrCode } from "./TotpQrCode";

/**
 * The one enrolment step (spec 48, RADD-1279): scan the QR (or paste the
 * secret), then prove it with a code. Shared by the Profile panel's
 * self-service setup and the sign-in page's forced enrolment, which differ
 * only in how the confirm is sent (a session vs. an enrolment ticket).
 */
export function TotpEnrolmentStep({
  setup,
  confirming,
  error,
  onConfirm,
  confirmLabel = "Confirm and enable",
  intro,
}: {
  setup: TotpSetup;
  confirming: boolean;
  error?: string;
  onConfirm: (code: string) => void;
  confirmLabel?: string;
  intro?: ReactNode;
}) {
  const [code, setCode] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (code.trim()) onConfirm(code.trim());
  };
  return (
    // A CONTAINER query, not a viewport one: the same step sits in the 384px
    // sign-in card and the wide Profile page, and only its own width says
    // whether the QR and the secret fit side by side.
    <div className="@container flex max-w-xl flex-col gap-4 rounded-lg border border-subtle bg-surface/40 p-4">
      {intro}
      <div className="flex flex-col items-center gap-4 @lg:flex-row @lg:items-start">
        <TotpQrCode uri={setup.otpauth_uri} />
        <div className="flex min-w-0 flex-1 flex-col gap-3 self-stretch">
          <p className="text-[13px] text-fg">
            Scan the code with your authenticator app (Google Authenticator, 1Password, Aegis, …).
            Can&rsquo;t scan? Add the secret below as a time-based (TOTP) entry.
          </p>
          <CopyValue label="Secret" value={setup.secret} secret mono size="md" />
        </div>
      </div>
      <form onSubmit={submit} className="flex flex-col gap-3 @md:flex-row @md:items-end">
        <TextField
          label="Code from the app"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={code}
          onChange={(event) => setCode(event.target.value)}
          placeholder="123456"
          error={error}
        />
        <Button type="submit" disabled={confirming || !code.trim()} className="justify-center whitespace-nowrap">
          <ShieldCheck size={14} aria-hidden />
          {confirming ? "Confirming…" : confirmLabel}
        </Button>
      </form>
    </div>
  );
}

/** The freshly-minted recovery codes — plaintext exists only in this render
 * (only hashes are stored), so the panel holds the user here until they say
 * they've saved them. */
export function RecoveryCodesOnce({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  return (
    <div className="flex max-w-xl flex-col gap-3 rounded-lg border border-subtle bg-surface/40 p-4">
      <p className="flex items-center gap-2 text-[13px] font-medium text-heading">
        <ShieldCheck size={15} className="shrink-0 text-emerald-400" aria-hidden />
        Save your recovery codes
      </p>
      <p className="text-xs text-fg-secondary">
        Each code signs you in once if your authenticator is gone. They are shown{" "}
        <strong>only now</strong> — store them with your passwords or print them.
      </p>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 rounded-md border border-strong bg-base px-4 py-3 font-mono text-[13px] text-heading">
        {codes.map((recoveryCode) => (
          <span key={recoveryCode}>{recoveryCode}</span>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <CopyAllButton value={codes.join("\n")} />
        <Button onClick={onDone}>I saved them</Button>
      </div>
    </div>
  );
}

function CopyAllButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard unavailable — the codes stay selectable above.
    }
  };
  return (
    <Button variant="ghost" className="border border-strong" onClick={() => void copy()}>
      {copied ? (
        <>
          <Check size={14} className="text-emerald-400" aria-hidden />
          Copied
        </>
      ) : (
        <>
          <Copy size={14} aria-hidden />
          Copy all
        </>
      )}
    </Button>
  );
}

