"""Enums and constants for SSO (spec 40 → spec 110: multi-provider registry)."""

from enum import StrEnum

# Short-lived cookie carrying the in-flight authorization request's state/nonce/
# PKCE verifier + the provider it belongs to (JSON). HttpOnly; validated + cleared
# on the callback.
OIDC_FLOW_COOKIE = "radd_oidc_flow"
OIDC_FLOW_TTL_SECONDS = 600


class SsoKind(StrEnum):
    """Which IdP a provider row talks to. Every kind runs the SAME OIDC
    code+PKCE engine — a kind only supplies discovery defaults and the
    identity claims worth trusting, never a separate flow (spec 110)."""

    GOOGLE = "google"  # accounts.google.com; `hd` carries the Workspace domain
    OIDC = "oidc"  # any standards-compliant issuer (Okta, Keycloak, Entra…)


class SsoProviderSource(StrEnum):
    """Where a provider row came from — env-seeded rows are ordinary editable rows."""

    ENV = "env"
    USER = "user"


# Discovery defaults per kind. GOOGLE is pinned because Google's issuer is a
# fixed, well-known URL — an admin should paste a client id/secret and nothing else.
KIND_DEFAULTS: dict[SsoKind, dict[str, str]] = {
    SsoKind.GOOGLE: {
        "issuer": "https://accounts.google.com",
        "scopes": "openid email profile",
        "name": "Google",
    },
    SsoKind.OIDC: {
        "issuer": "",
        "scopes": "openid email profile",
        "name": "SSO",
    },
}


class SsoEvent(StrEnum):
    LOGIN = "sso.login"  # a successful OIDC sign-in (audit)
    IDENTITY_LINKED = "sso.identity_linked"  # a provider identity bound to an existing account


class SsoEntity(StrEnum):
    SSO = "sso"
    PROVIDER = "sso_provider"
    IDENTITY = "user_identity"


# Explicit opt-out of the signup allowlist, for an instance whose IdP is already
# the gate (a private Keycloak holding staff only). Spelled out rather than
# implied by an empty list, so "no domains" can keep meaning "no signups".
WILDCARD_DOMAIN = "*"


