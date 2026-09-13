import { useState, type FormEvent } from "react";
import { resetAccountSession } from "../lib/account-session";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, errorMessage } from "../lib/api";
import { isTotpRequired, ldapLogin, login, totpLogin, safeNextPath } from "../lib/auth";
import { On401, RoutePath } from "../lib/constants";
import { Button } from "../components/Button";
import { RaddTile } from "../components/RaddMark";
import { SsoButtons } from "../components/SsoButtons";
import { TextField } from "../components/TextField";

const INVALID_CREDENTIALS_MESSAGE = "Invalid email or password.";
const INVALID_LDAP_CREDENTIALS_MESSAGE = "Invalid username or password.";
/** A wrong code on /auth/login/totp — the backend 401s uniformly (spec 48). */
const INVALID_TOTP_MESSAGE = "Invalid email, password, or code.";
const AUTH_NOT_DEPLOYED_MESSAGE = "Sign-in is unavailable on this server. Contact your administrator.";

/** Which credential form is showing (spec 42 adds the directory option). */
const LoginMode = {
  email: "email",
  directory: "directory",
} as const;
type LoginModeValue = (typeof LoginMode)[keyof typeof LoginMode];

type LoginOptions = { sso_enabled: boolean; ldap_enabled: boolean };

export function LoginPage() {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<LoginModeValue>(LoginMode.email);
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  // TOTP second step (spec 48): a 401 "totp_required" reveals the code field
  // and reroutes the submit through /auth/login/totp.
  const [totpRequired, setTotpRequired] = useState(false);
  const [code, setCode] = useState("");

  const { data: options } = useQuery({
    queryKey: ["loginOptions"],
    queryFn: ({ signal }) => api.get<LoginOptions>("/instance/login-options", { signal, on401: On401.throw }),
    staleTime: Infinity,
    retry: false,
  });
  const directory = mode === LoginMode.directory && options?.ldap_enabled;

  const submit = useMutation({
    mutationFn: () =>
      directory
        ? ldapLogin({ username: username.trim(), password })
        : totpRequired
          ? totpLogin({ email: email.trim().toLowerCase(), password, code: code.trim() })
          : login({ email: email.trim().toLowerCase(), password }),
    onSuccess: async () => {
      await resetAccountSession(queryClient);
      window.location.assign(next ?? RoutePath.home);
    },
    onError: (error) => {
      if (isTotpRequired(error)) setTotpRequired(true);
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

  const error = submit.error;
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

        <form
          onSubmit={onSubmit}
          className="flex flex-col gap-4 rounded-lg border border-subtle bg-surface/40 p-5"
        >
          {options?.ldap_enabled && (
            <ModeToggle
              mode={mode}
              onChange={(next) => {
                setMode(next);
                setTotpRequired(false);
                setCode("");
                submit.reset();
              }}
            />
          )}
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
        </form>

        <SsoButtons next={next} />
      </div>
    </main>
  );
}

/** Email / Directory switch — only rendered when the instance has LDAP configured. */
function ModeToggle({
  mode,
  onChange,
}: {
  mode: LoginModeValue;
  onChange: (mode: LoginModeValue) => void;
}) {
  const tab = (value: LoginModeValue, label: string) => (
    <button
      type="button"
      onClick={() => onChange(value)}
      className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium ${
        mode === value
          ? "bg-strong/70 text-heading"
          : "text-fg-secondary hover:text-fg"
      }`}
    >
      {label}
    </button>
  );
  return (
    <div className="flex gap-1 rounded-lg bg-elevated/60 p-1">
      {tab(LoginMode.email, "Email")}
      {tab(LoginMode.directory, "Directory")}
    </div>
  );
}
