"""Read/write models for the SSO provider registry (spec 110).

`client_secret` is write-only throughout: reads carry `has_client_secret` so a
form can show "configured" without the value ever reaching a browser, and an
empty secret on update means "keep the stored one".
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from .types import SsoKind


class SsoDefaultGrant(BaseModel):
    """One role a new account receives, at one scope (RADD-780).

    Mirrors `global_role_grants`: `project_id` null = instance-wide. The same
    (role, scope) pair the Grant Role dialog produces everywhere else, because
    these are a template for exactly those rows.
    """

    model_config = ConfigDict(from_attributes=True)

    role_id: uuid.UUID
    project_id: uuid.UUID | None = None


class SsoProviderBase(BaseModel):
    name: str = ""  # "" = the kind's default label ("Google")
    enabled: bool = True
    position: int = 0
    issuer: str = ""  # "" = the kind's default (Google's is pinned)
    client_id: str = ""
    scopes: str = ""  # "" = the kind's default
    auto_provision: bool = True
    allowed_signup_domains: list[str] = Field(default_factory=list)
    require_verified_email: bool = True
    group_claim: str = "groups"
    admin_groups: str = ""
    #: What a NEW account gets from this provider (RADD-780): any number of
    #: roles, each global or scoped to one project. Empty = the Baseline alone.
    default_grants: list["SsoDefaultGrant"] = Field(default_factory=list)
    #: Teams a new account joins (RADD-781). LOCAL teams only — a
    #: directory-linked team's membership belongs to its AD group.
    default_team_ids: list[uuid.UUID] = Field(default_factory=list)


class SsoProviderCreate(SsoProviderBase):
    kind: SsoKind
    client_secret: str = ""


class SsoProviderUpdate(BaseModel):
    """Every field optional — PATCH semantics (`exclude_unset` drives the write)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    enabled: bool | None = None
    position: int | None = None
    issuer: str | None = None
    client_id: str | None = None
    client_secret: str | None = None  # "" / omitted = keep the stored secret
    scopes: str | None = None
    auto_provision: bool | None = None
    allowed_signup_domains: list[str] | None = None
    require_verified_email: bool | None = None
    group_claim: str | None = None
    admin_groups: str | None = None
    #: Full replacement when present, omitted = leave alone (the views/sharing
    #: idiom). An empty list therefore CLEARS them, which is how "new accounts
    #: get nothing extra" is said once grants have been configured.
    default_grants: list["SsoDefaultGrant"] | None = None
    default_team_ids: list[uuid.UUID] | None = None


class SsoProviderRead(SsoProviderBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: SsoKind
    source: str
    has_client_secret: bool
    # False when the row can't complete a flow yet (no client id/secret/issuer) —
    # the admin page explains WHY a provider isn't on the login page.
    configured: bool = True
    redirect_uri: str = ""  # what to paste into the IdP's console


class SsoProviderPublic(BaseModel):
    """The unauthenticated login page's view: enough to draw a button, nothing more."""

    id: uuid.UUID
    name: str
    kind: SsoKind


class SsoIdentityRead(BaseModel):
    """A federated login bound to an account (Settings → Users, profile)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_id: uuid.UUID
    provider_name: str = ""
    subject: str
    email: str
