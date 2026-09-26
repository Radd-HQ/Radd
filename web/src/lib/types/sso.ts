/**
 * The login page's sign-in buttons (spec 110). They render BEFORE sign-in, when no plugin remote
 * can load, so this public shape stays in the host; the provider registry's admin vocabulary is
 * the sso plugin's own (RADD-1380).
 */

/** Which IdP a button signs in with — decides the mark drawn beside its label. */
export const SsoKind = {
  google: "google",
  oidc: "oidc",
  github: "github",
} as const;
export type SsoKindValue = (typeof SsoKind)[keyof typeof SsoKind];

/** GET /auth/sso/providers (unauthenticated) — enough to draw a login button. */
export interface SsoProviderPublic {
  id: string;
  name: string;
  kind: SsoKindValue;
}
