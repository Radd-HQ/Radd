import { useState, type FormEvent } from "react";
import { resetAccountSession } from "../lib/account-session";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, errorMessage } from "../lib/api";
import { enrollmentTicket, isTotpRequired, ldapLogin, login, totpLogin, safeNextPath } from "../lib/auth";
import { On401, RoutePath } from "../lib/constants";
import { Button } from "../components/Button";
import { RaddTile } from "../components/RaddMark";
import { MfaEnrollment } from "../components/MfaEnrollment";
import { SsoButtons } from "../components/SsoButtons";
import { TextField } from "../components/TextField";

import { Spinner } from "../components/Spinner";
type LoginOptions = { ldap_enabled: boolean; sso_enabled: boolean };

const INVALID_CREDENTIALS_MESSAGE = "Invalid email or password.";
const INVALID_LDAP_CREDENTIALS_MESSAGE = "Invalid username or password.";
/** A wrong code on /auth/login/totp — the backend 401s uniformly (spec 48). */
const INVALID_TOTP_MESSAGE = "Invalid email, password, or code.";
const AUTH_NOT_DEPLOYED_MESSAGE = "Sign-in is unavailable on this server. Contact your administrator.";

export function LoginPage() {
  const queryClient = useQueryClient();
  const [localOpen, setLocalOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  // TOTP second step (spec 48): a 401 "totp_required" reveals the code field
  // and reroutes the submit through /auth/login/totp.
  const [totpRequired, setTotpRequired] = useState(false);
  const [code, setCode] = useState("");
  // RADD-1279: the instance requires two-factor and this account has none —
  // the refused login carried a ticket, and enrolment replaces the form.
  const [ticket, setTicket] = useState<string | null>(null);

  const optionsQuery = useQuery({
    queryKey: ["loginOptions"],
    queryFn: ({ signal }) => api.get<LoginOptions>("/instance/login-options", { signal, on401: On401.throw }),
    staleTime: 0,
    retry: false,
  });
  const directory = optionsQuery.data?.ldap_enabled === true && !localOpen;
  const toggleLocal = () => {
    setLocalOpen(open => !open);
    setPassword("");
    setTotpRequired(false);
    setCode("");
    submit.reset();
  };

  const submit = useMutation({
    mutationFn: () =>
      directory
        ? ldapLogin({ username: username.trim(), password })
        : totpRequired
          ? totpLogin({ email: email.trim().toLowerCase(), password, code: code.trim() })
          : login({ email: email.trim().toLowerCase(), password }),
    onSuccess: () => enterApp(),
    onError: (error) => {
      if (isTotpRequired(error)) setTotpRequired(true);
      setTicket(enrollmentTicket(error));
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit.mutate();
  };

  // A refused SSO callback redirects back here with its reason (spec 110) —
  // "you can't sign up from this domain" is a message a person has to READ, and
  // that leg runs in the address bar where a JSON 403 body would be the page.
  // Read once on mount: the URL doesn't change under us.
  const [ssoError] = useState(() =>
    new URLSearchParams(window.location.search).get("sso_error"),
  );
  // Spec 121: where to return after signing in (a public page the visitor was
  // reading). Same-origin paths only.
  const [next] = useState(() => safeNextPath(new URLSearchParams(window.location.search).get("next")));

  async function enterApp() {
    await resetAccountSession(queryClient);
    window.location.assign(next ?? RoutePath.home);
  }

  const error = ticket ? null : submit.error;
  const authMissing = error instanceof ApiError && error.status === 404;
  // "totp_required" isn't a failure to show — the revealed code field is the
  // message. Any other 401 keeps the mode's invalid-credentials text; once the
  // code field is up, a 401 from the totp endpoint means a wrong code too.
  const errorText = !error
    ? null
    : authMissing
      ? AUTH_NOT_DEPLOYED_MESSAGE
      : isTotpRequired(error)
        ? null
        : error instanceof ApiError && error.status === 401
          ? directory
            ? INVALID_LDAP_CREDENTIALS_MESSAGE
            : totpRequired
              ? INVALID_TOTP_MESSAGE
              : INVALID_CREDENTIALS_MESSAGE
          : errorMessage(error);

  return (
    <main className="flex min-h-screen items-center justify-center bg-base px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <RaddTile className="size-8 rounded-lg" />
          <div>
            <h1 className="text-base font-semibold text-heading">Radd</h1>
            <p className="text-xs text-fg-muted">Sign in to your tracker</p>
          </div>
        </div>

        {ssoError && (
          <div className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-xs text-amber-300">
            {ssoError}
          </div>
        )}

        {optionsQuery.isPending && !localOpen && <Spinner label="Loading sign-in options…" />}
        {optionsQuery.isError && (
          <p className="mb-3 text-xs text-fg-muted">
            Could not load sign-in options. Local account sign-in is still available.{" "}
            <button type="button" className="underline" onClick={() => void optionsQuery.refetch()}>Retry</button>
          </p>
        )}
        {ticket && (
          <MfaEnrollment
            ticket={ticket}
            onSignedIn={() => void enterApp()}
            onRestart={() => {
              setTicket(null);
              setPassword("");
              submit.reset();
            }}
          />
        )}
        {!ticket && (directory || localOpen) && <form
          onSubmit={onSubmit}
          className="flex flex-col gap-4 rounded-lg border border-subtle bg-surface/40 p-5"
        >
          <p className="text-xs text-fg-muted">
            {directory ? "Use your directory username and AD / LDAP password." : "Use your local Radd account password. Your directory password does not apply here."}
          </p>
          {directory ? (
            <TextField
              label="Username"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="jdoe"
              required
              autoFocus
            />
          ) : (
            <TextField
              label="Email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              required
              autoFocus
            />
          )}
          <TextField
            label="Password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
          {totpRequired && !directory && (
            <TextField
              label="Authentication code"
              autoComplete="one-time-code"
              maxLength={12}
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="123456"
              hint="Enter the 6-digit code from your authenticator app — or one of your recovery codes if the app is gone."
              required
              autoFocus
            />
          )}
          {errorText && (
            <p className={`text-xs ${authMissing ? "text-amber-400" : "text-red-400"}`}>
              {errorText}

            </p>
          )}
          <Button type="submit" disabled={submit.isPending} className="justify-center">
            {submit.isPending ? "Signing in…" : "Sign in"}
          </Button>
        </form>}

        {!ticket && <button type="button" disabled={submit.isPending} aria-expanded={localOpen}
          className="mt-4 block w-full text-center text-xs text-fg-muted underline hover:text-fg"
          onClick={toggleLocal}>
          {localOpen ? "Close local account sign-in" : "Sign in with a local account"}
        </button>}
        {!ticket && <SsoButtons next={next} />}
      </div>
    </main>
  );
}
