"""The wire to the identity provider (spec 110 → spec 121).

Everything here is one of three HTTP conversations: the endpoint document (a
discovery fetch, or the kind's pinned endpoints), the code→token exchange, and
turning the token response into CLAIMS — which is where kinds differ. An OIDC
kind hands back an `id_token` to verify against the issuer's JWKS; a plain
OAuth2 kind (GitHub) hands back an access token to spend on a profile API. Both
strategies produce the SAME claim-shaped dict, so `service.provision` never
learns which kind signed the person in.
"""

import logging
import time
import uuid

import httpx
import jwt
from jwt import PyJWKClient

from radd.config import settings
from radd.exceptions import ForbiddenError

from . import registry
from .models import SsoProvider
from .types import KIND_DEFAULTS, KindDefaults, ProfileStrategy, SsoKind

logger = logging.getLogger(__name__)

# Test seam: set to an httpx.MockTransport to exercise the full request path
# without a network (None = httpx's real transport). The ai/client.py idiom.
transport: httpx.AsyncBaseTransport | None = None

# Per-provider caches — an instance runs several issuers now, so a single
# module-level cache would have served Google's metadata for Okta's flow.
# Metadata entries carry a fetch time and expire (RADD-899): an IdP that moves
# its endpoints used to keep failing until a Radd restart. Key rotation was
# never the problem — PyJWKClient refreshes keys itself.
METADATA_TTL_SECONDS = 3600.0
_metadata_cache: dict[uuid.UUID, tuple[float, dict]] = {}
_jwks_clients: dict[uuid.UUID, PyJWKClient] = {}

ID_TOKEN_ALGORITHMS = ("RS256", "ES256")
JSON_ACCEPT = {"Accept": "application/json"}  # GitHub answers form-encoded without it


def defaults_of(provider: SsoProvider) -> KindDefaults:
    return KIND_DEFAULTS[SsoKind(provider.kind)]


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=settings.sso_http_timeout_seconds, transport=transport)


def invalidate_caches(provider_id: uuid.UUID | None = None) -> None:
    """Editing a row must not leave the old issuer's discovery document live."""
    if provider_id is None:
        _metadata_cache.clear()
        _jwks_clients.clear()
        return
    _metadata_cache.pop(provider_id, None)
    _jwks_clients.pop(provider_id, None)


# --- endpoints ----------------------------------------------------------------


async def metadata(provider: SsoProvider) -> dict:
    """The provider's endpoint document, cached per provider with a TTL (RADD-899).

    A discovery kind fetches `/.well-known/openid-configuration`; a pinned kind
    synthesizes the same shape from its defaults, so every caller reads one
    document regardless of where the endpoints came from."""
    cached = _metadata_cache.get(provider.id)
    if cached is not None and time.monotonic() - cached[0] < METADATA_TTL_SECONDS:
        return cached[1]
    defaults = defaults_of(provider)
    if defaults.discovery:
        document = await _discover(registry.issuer_of(provider))
    else:
        document = _pinned_document(provider, defaults)
    _metadata_cache[provider.id] = (time.monotonic(), document)
    return document


async def _discover(issuer: str) -> dict:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    async with _client() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


def _pinned_document(provider: SsoProvider, defaults: KindDefaults) -> dict:
    return {
        "issuer": registry.issuer_of(provider),
        "authorization_endpoint": defaults.authorization_endpoint,
        "token_endpoint": defaults.token_endpoint,
        "profile_url": defaults.profile_url,
        "emails_url": defaults.emails_url,
    }


def _jwks(provider: SsoProvider, jwks_uri: str) -> PyJWKClient:
    client = _jwks_clients.get(provider.id)
    if client is None:
        client = PyJWKClient(jwks_uri)
        _jwks_clients[provider.id] = client
    return client


# --- code → claims ------------------------------------------------------------


async def exchange_code(provider: SsoProvider, code: str, flow: dict, redirect_uri: str) -> dict:
    """Code → claims: the token exchange, then the kind's profile strategy."""
    tokens = await exchange_tokens(provider, code, flow, redirect_uri)
    return await profile(provider, tokens, flow)


async def exchange_tokens(provider: SsoProvider, code: str, flow: dict, redirect_uri: str) -> dict:
    meta = await metadata(provider)
    async with _client() as client:
        response = await client.post(
            meta["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": provider.client_id,
                "client_secret": provider.client_secret,
                "code_verifier": flow["verifier"],
            },
            headers=JSON_ACCEPT,
        )
        response.raise_for_status()
        return response.json()


async def profile(provider: SsoProvider, tokens: dict, flow: dict) -> dict:
    """The token response → the claim-shaped dict `service.provision` consumes:
    `sub`, `email`, `email_verified`, `name`, `picture` (+ whatever the IdP adds)."""
    strategy = defaults_of(provider).profile
    if strategy is ProfileStrategy.ID_TOKEN:
        return await _id_token_claims(provider, tokens, flow)
    return await _oauth_profile_claims(provider, tokens)


async def _id_token_claims(provider: SsoProvider, tokens: dict, flow: dict) -> dict:
    id_token = tokens.get("id_token")
    if not id_token:
        raise ForbiddenError(f"{provider.name} returned no id_token")
    meta = await metadata(provider)
    signing_key = _jwks(provider, meta["jwks_uri"]).get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=list(ID_TOKEN_ALGORITHMS),
        audience=provider.client_id,
        issuer=meta["issuer"],
    )
    if claims.get("nonce") != flow["nonce"]:
        raise ForbiddenError("sign-in nonce mismatch — retry")
    return claims


async def _oauth_profile_claims(provider: SsoProvider, tokens: dict) -> dict:
    """GitHub's shape. The subject is the NUMERIC id — `login` is renameable, and
    a renamed login must not fork the account (the spec-110 pinning rule).

    The profile's `email` is whatever the person chose to show publicly, often
    nothing; the emails API says which address is primary AND verified. No
    verified primary → `email_verified` False, so `require_verified_email`
    refuses it through the same path an unverified OIDC claim takes."""
    access_token = tokens.get("access_token")
    if not access_token:
        raise ForbiddenError(f"{provider.name} returned no access token")
    meta = await metadata(provider)
    headers = {**JSON_ACCEPT, "Authorization": f"Bearer {access_token}"}
    async with _client() as client:
        response = await client.get(meta["profile_url"], headers=headers)
        response.raise_for_status()
        payload = response.json()
        response = await client.get(meta["emails_url"], headers=headers)
        response.raise_for_status()
        emails = response.json()
    if not isinstance(emails, list):
        emails = []
    primary = next((e for e in emails if e.get("primary")), None)
    verified = primary is not None and bool(primary.get("verified"))
    email = (primary or {}).get("email") or payload.get("email") or ""
    return {
        "sub": str(payload["id"]),
        "login": payload.get("login") or "",
        "name": payload.get("name") or payload.get("login") or "",
        "email": email,
        "email_verified": verified,
        "picture": payload.get("avatar_url") or "",
    }
