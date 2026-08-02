import { api, ApiError } from "./api";
import { ApiPath, On401 } from "./constants";
import type { LoginRequest, Me, TotpLoginRequest } from "./types";

/**
 * Auth session state, resolved from GET /auth/me on boot.
 *
 * Degradation (Wave 1): while the auth backend module is still landing,
 * /auth/me returns 404. We treat that as "anonymous dev mode": the app stays
 * usable against the open API instead of bouncing to a login that can't work.
 */
export const AuthStatus = {
  /** /auth/me returned a user. */
  authenticated: "authenticated",
  /** /auth/me 401'd — auth is live and there is no session. */
  unauthenticated: "unauthenticated",
  /** /auth/me 404'd — auth module not deployed yet; API is open (dev). */
  anonymousDev: "anonymous_dev",
} as const;
export type AuthStatusValue = (typeof AuthStatus)[keyof typeof AuthStatus];

export type AuthState =
  | { status: typeof AuthStatus.authenticated; user: Me }
  | { status: typeof AuthStatus.unauthenticated; user: null }
  | { status: typeof AuthStatus.anonymousDev; user: null };

export async function fetchAuthState(): Promise<AuthState> {
  try {
    const user = await api.get<Me>(ApiPath.me, { on401: On401.throw });
    return { status: AuthStatus.authenticated, user };
  } catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 401) return { status: AuthStatus.unauthenticated, user: null };
      if (error.status === 404) return { status: AuthStatus.anonymousDev, user: null };
    }
    throw error;
  }
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
