import { setStorageAccount } from "./account-storage";
import { api, ApiError, setAnonymousMode } from "./api";
import { ApiPath, On401 } from "./constants";
import type { LoginRequest, Me, TotpLoginRequest } from "./types";

/** Authentication fails closed when the backend is missing or unavailable. */
export const AuthStatus = {
  /** /auth/me returned a user. */
  authenticated: "authenticated",
  /** /auth/me 401'd — auth is live and there is no session. */
  unauthenticated: "unauthenticated",
  /** Spec 121: no session, but the server answered as the Anyone principal —
   *  the shell renders for a visitor, reading what public projects allow. */
  anonymous: "anonymous",
} as const;

export type AuthState =
  | { status: typeof AuthStatus.authenticated; user: Me }
  | { status: typeof AuthStatus.unauthenticated; user: null }
  | { status: typeof AuthStatus.anonymous; user: Me };

export async function fetchAuthState(signal?: AbortSignal): Promise<AuthState> {
  try {
    const user = await api.get<Me>(ApiPath.me, { on401: On401.throw, signal });
    if (user.anonymous) {
      setAnonymousMode(true);
      return { status: AuthStatus.anonymous, user };
    }
    setAnonymousMode(false);
    setStorageAccount(user.id);
    return { status: AuthStatus.authenticated, user };
  } catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 401) return { status: AuthStatus.unauthenticated, user: null };

    }
    throw error;
  }
}

/** A return path a sign-in may honour: same-origin, absolute-path only. */
export function safeNextPath(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/login")) return null;
  return next;
}

/** The current page as a `next` value for a sign-in link. */
export function currentPath(): string {
  return window.location.pathname + window.location.search;
}

/** POST /auth/login — 204 + HttpOnly session cookie on success. */
export function login(body: LoginRequest): Promise<void> {
  return api.post<void>(ApiPath.login, body, { on401: On401.throw });
}

/** POST /auth/ldap/login (spec 42) — directory sign-in, same 204 + cookie shape. */
export function ldapLogin(body: { username: string; password: string }): Promise<void> {
  return api.post<void>(ApiPath.ldapLogin, body, { on401: On401.throw });
}

/**
 * Backend 401 detail signalling a TOTP-enabled account (spec 48): the password
 * was right but no cookie was set — repeat via /auth/login/totp with a code.
 */
export const TOTP_REQUIRED_DETAIL = "totp_required";

export function isTotpRequired(error: unknown): boolean {
  return (
    error instanceof ApiError && error.status === 401 && error.detail === TOTP_REQUIRED_DETAIL
  );
}

/** POST /auth/login/totp (spec 48) — email + password + code, 204 + cookie. */
export function totpLogin(body: TotpLoginRequest): Promise<void> {
  return api.post<void>(ApiPath.loginTotp, body, { on401: On401.throw });
}

/** POST /auth/logout — 204, clears the session. */
export function logout(): Promise<void> {
  return api.post<void>(ApiPath.logout, undefined, { on401: On401.throw });
}
