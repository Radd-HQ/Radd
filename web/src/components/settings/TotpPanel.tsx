import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, ShieldCheck, ShieldOff } from "lucide-react";
import { ApiError, api, errorMessage } from "../../lib/api";
import { ApiPath, On401 } from "../../lib/constants";
import { queryKeys, totpStatusQuery } from "../../lib/queries";
import type { TotpRecoveryCodes, TotpSetup, TotpStatus } from "../../lib/types";
import { Button } from "../Button";
import { TextField } from "../TextField";
import { ErrorText } from "../ErrorText";
import { CopyValue } from "./CopyValue";

const INVALID_CODE_MESSAGE = "Invalid code.";

/** Inline message for a confirm/disable failure: a 401 means "wrong code". */
function codeError(error: unknown): string | null {
  if (!error) return null;
  if (error instanceof ApiError && error.status === 401) return INVALID_CODE_MESSAGE;
  return errorMessage(error);
}

/**
 * Two-factor authentication panel on the Profile page (spec 48). Disabled:
 * Enable → shows the new secret + otpauth URI (QR-less — paste into an
 * authenticator app) with a confirm-code input. Enabled: green badge + a
 * disable flow that requires a current code (DELETE /auth/totp {code}).
 */
export function TotpPanel() {
  const status = useQuery(totpStatusQuery);

  if (status.isPending) {
    return <p className="text-xs text-fg-muted">Loading two-factor status…</p>;
  }
  if (status.isError) {
    return (
      <p className="text-xs text-red-400">
        Failed to load two-factor status: {errorMessage(status.error)}
      </p>
    );
  }
  return status.data.enabled ? (
    <EnabledPanel status={status.data} />
  ) : (
    <SetupPanel pending={status.data.pending} />
  );
}

/** Disabled (or setup-pending) state: start setup, show the secret, confirm. */
function SetupPanel({ pending }: { pending: boolean }) {
  const queryClient = useQueryClient();
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [confirmCode, setConfirmCode] = useState("");
  const [minted, setMinted] = useState<string[] | null>(null);

  const start = useMutation({
    mutationFn: () => api.post<TotpSetup>(ApiPath.totpSetup),
    onSuccess: setSetup,
  });

  const confirm = useMutation({
    // A wrong code 401s — surface it inline, don't bounce to /login.
    mutationFn: (code: string) =>
      api.post<TotpRecoveryCodes>(ApiPath.totpConfirm, { code }, { on401: On401.throw }),
    onSuccess: (result) => {
      setSetup(null);
      setConfirmCode("");
      setMinted(result.recovery_codes);
      void queryClient.invalidateQueries({ queryKey: queryKeys.totp });
    },
  });

  // Enrollment just finished: the one moment the codes exist in plaintext.
  if (minted) {
    return <RecoveryCodesOnce codes={minted} onDone={() => setMinted(null)} />;
  }

  if (!setup) {
    return (
      <div className="flex flex-col items-start gap-3">
        <p className="flex items-center gap-2 text-[13px] text-fg-secondary">
          <ShieldOff size={15} className="shrink-0 text-fg-muted" aria-hidden />
          Two-factor authentication is off — sign-in only asks for your password.
        </p>
        {pending && (
          <p className="text-xs text-amber-400">
            A previous setup was never confirmed. Starting again generates a new secret.
          </p>
        )}
        <Button onClick={() => start.mutate()} disabled={start.isPending}>
          {start.isPending ? "Preparing…" : pending ? "Restart setup" : "Enable"}
        </Button>
        {start.isError && <ErrorText error={start.error} />}
      </div>
    );
  }

  const onConfirm = (event: FormEvent) => {
    event.preventDefault();
    if (confirmCode.trim()) confirm.mutate(confirmCode.trim());
  };

  return (
    <div className="flex max-w-xl flex-col gap-4 rounded-lg border border-subtle bg-surface/40 p-4">
      <p className="text-[13px] text-fg">
        Add this secret to your authenticator app (Google Authenticator, 1Password, Aegis, …) —
        paste the secret as a time-based (TOTP) entry, or use the full otpauth URI. Then enter a
        generated code below to turn two-factor on.
      </p>
      <CopyValue label="Secret" value={setup.secret} secret mono size="md" />
      <CopyValue label="otpauth URI" value={setup.otpauth_uri} secret size="md" />
      <form onSubmit={onConfirm} className="flex items-end gap-3">
        <TextField
          label="Confirm code"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={confirmCode}
          onChange={(event) => setConfirmCode(event.target.value)}
          placeholder="123456"
          error={codeError(confirm.error) ?? undefined}
        />
        <Button type="submit" disabled={confirm.isPending || !confirmCode.trim()}>
          <ShieldCheck size={14} aria-hidden />
          {confirm.isPending ? "Confirming…" : "Confirm and enable"}
        </Button>
      </form>
    </div>
  );
}

/** Enabled state: green badge + a two-step disable that requires a current code. */
function EnabledPanel({ status }: { status: TotpStatus }) {
  const queryClient = useQueryClient();
  const [disabling, setDisabling] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [regenCode, setRegenCode] = useState("");
  const [minted, setMinted] = useState<string[] | null>(null);
  const [code, setCode] = useState("");

  const regenerate = useMutation({
    mutationFn: (currentCode: string) =>
      api.post<TotpRecoveryCodes>(
        ApiPath.totpRecoveryCodes,
        { code: currentCode },
        { on401: On401.throw },
      ),
    onSuccess: (result) => {
      setRegenerating(false);
      setRegenCode("");
      setMinted(result.recovery_codes);
      void queryClient.invalidateQueries({ queryKey: queryKeys.totp });
    },
  });

  const disable = useMutation({
    // A wrong code 401s — surface it inline, don't bounce to /login.
    mutationFn: (currentCode: string) =>
      api.delete<void>(ApiPath.totp, { body: { code: currentCode }, on401: On401.throw }),
    onSuccess: () => {
      setDisabling(false);
      setCode("");
      void queryClient.invalidateQueries({ queryKey: queryKeys.totp });
    },
  });

  const onDisable = (event: FormEvent) => {
    event.preventDefault();
    if (code.trim()) disable.mutate(code.trim());
  };

  const onRegenerate = (event: FormEvent) => {
    event.preventDefault();
    if (regenCode.trim()) regenerate.mutate(regenCode.trim());
  };

  if (minted) {
    return <RecoveryCodesOnce codes={minted} onDone={() => setMinted(null)} />;
  }

  return (
    <div className="flex flex-col items-start gap-3">
      <p className="flex items-center gap-2 text-[13px] text-fg-secondary">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-300">
          <ShieldCheck size={13} aria-hidden />
          Enabled
        </span>
        Sign-in asks for a code from your authenticator app.
      </p>
      <p className="text-xs text-fg-muted">
        {status.recovery_codes_remaining > 0
          ? `${status.recovery_codes_remaining} unused recovery code${
              status.recovery_codes_remaining === 1 ? "" : "s"
            } — each signs you in once if the app is gone.`
          : "No recovery codes left — generate a fresh batch before you need one."}
      </p>
      {regenerating ? (
        <form onSubmit={onRegenerate} className="flex items-end gap-3">
          <TextField
            label="Current code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={regenCode}
            onChange={(event) => setRegenCode(event.target.value)}
            placeholder="123456"
            hint="New codes replace every old one, used or not."
            error={codeError(regenerate.error) ?? undefined}
            autoFocus
          />
          <Button type="submit" disabled={regenerate.isPending || !regenCode.trim()}>
            {regenerate.isPending ? "Generating…" : "Generate new codes"}
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setRegenerating(false);
              setRegenCode("");
              regenerate.reset();
            }}
          >
            Cancel
          </Button>
        </form>
      ) : (
        <Button variant="ghost" className="border border-strong" onClick={() => setRegenerating(true)}>
          New recovery codes…
        </Button>
      )}
      {disabling ? (
        <form onSubmit={onDisable} className="flex items-end gap-3">
          <TextField
            label="Current code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={12}
            value={code}
            onChange={(event) => setCode(event.target.value)}
            placeholder="123456"
            hint="Disabling requires a current code from your app — a recovery code works too."
            error={codeError(disable.error) ?? undefined}
            autoFocus
          />
          <Button
            type="submit"
            variant="ghost"
            disabled={disable.isPending || !code.trim()}
            className="border border-strong hover:border-red-500/50 hover:text-red-300"
          >
            {disable.isPending ? "Disabling…" : "Confirm disable"}
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setDisabling(false);
              setCode("");
              disable.reset();
            }}
          >
            Keep enabled
          </Button>
        </form>
      ) : (
        <Button variant="ghost" className="border border-strong" onClick={() => setDisabling(true)}>
          <ShieldOff size={14} aria-hidden />
          Disable…
        </Button>
      )}
    </div>
  );
}

/** The freshly-minted recovery codes — plaintext exists only in this render
 * (only hashes are stored), so the panel holds the user here until they say
 * they've saved them. */
function RecoveryCodesOnce({ codes, onDone }: { codes: string[]; onDone: () => void }) {
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

