"""Enums and constants for SSO (spec 40 → spec 110: multi-provider registry)."""

from dataclasses import dataclass
from enum import StrEnum

# Short-lived cookie carrying the in-flight authorization request's state/nonce/
# PKCE verifier + the provider it belongs to (JSON). HttpOnly; validated + cleared
# on the callback.
OIDC_FLOW_COOKIE = "radd_oidc_flow"
OIDC_FLOW_TTL_SECONDS = 600


class SsoKind(StrEnum):
    """Which IdP a provider row talks to.

    Every kind runs the SAME engine — state + PKCE, one callback, identity
    pinned to the subject, the signup allowlist. A kind supplies its ENDPOINTS
    (discovered from the issuer, or pinned) and its PROFILE STRATEGY (an
    `id_token` to verify, or a profile API to call); it never forks the flow
    (spec 110, restated by spec 121 when GitHub — plain OAuth2 — arrived)."""

    GOOGLE = "google"  # accounts.google.com; `hd` carries the Workspace domain
    OIDC = "oidc"  # any standards-compliant issuer (Okta, Keycloak, Entra…)
    GITHUB = "github"  # github.com OAuth app: no discovery, no id_token


class ProfileStrategy(StrEnum):
    """How a kind turns the token response into identity claims."""

    ID_TOKEN = "id_token"  # OIDC: verify the JWT against the issuer's JWKS + nonce
    OAUTH_PROFILE = "oauth_profile"  # OAuth2: GET the profile + emails APIs with the access token


class SsoProviderSource(StrEnum):
    """Where a provider row came from — env-seeded rows are ordinary editable rows."""

    ENV = "env"
    USER = "user"


@dataclass(frozen=True)
class KindDefaults:
    """What a kind contributes: endpoints (discovered or pinned) + a profile strategy.

    `discovery` True = the issuer serves `/.well-known/openid-configuration` and
    the endpoints come from there; False = the endpoints below are the document.
    """

    name: str
    scopes: str
    issuer: str = ""  # "" = the admin must supply one (generic OIDC)
    discovery: bool = True
    profile: ProfileStrategy = ProfileStrategy.ID_TOKEN
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    profile_url: str = ""
    emails_url: str = ""


# Per-kind defaults. GOOGLE is pinned because Google's issuer is a fixed,
# well-known URL — an admin should paste a client id/secret and nothing else.
# GITHUB has no discovery document at all, so every endpoint is pinned here.
KIND_DEFAULTS: dict[SsoKind, KindDefaults] = {
    SsoKind.GOOGLE: KindDefaults(
        name="Google",
        scopes="openid email profile",
        issuer="https://accounts.google.com",
    ),
    SsoKind.OIDC: KindDefaults(
        name="SSO",
        scopes="openid email profile",
    ),
    SsoKind.GITHUB: KindDefaults(
        name="GitHub",
        scopes="read:user user:email",
        issuer="https://github.com",
        discovery=False,
        profile=ProfileStrategy.OAUTH_PROFILE,
        authorization_endpoint="https://github.com/login/oauth/authorize",
        token_endpoint="https://github.com/login/oauth/access_token",
        profile_url="https://api.github.com/user",
        emails_url="https://api.github.com/user/emails",
    ),
}


class SsoEvent(StrEnum):
    LOGIN = "sso.login"  # a successful OIDC sign-in (audit)
    IDENTITY_LINKED = "sso.identity_linked"  # a provider identity bound to an existing account


class SsoEntity(StrEnum):
    SSO = "sso"
    PROVIDER = "sso_provider"


# Explicit opt-out of the signup allowlist, for an instance whose IdP is already
# the gate (a private Keycloak holding staff only). Spelled out rather than
# implied by an empty list, so "no domains" can keep meaning "no signups".
WILDCARD_DOMAIN = "*"
