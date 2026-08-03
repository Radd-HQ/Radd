"""SSO provider registry + federated identities (spec 110).

Providers moved out of the environment and into the database for the same
reason AI providers did (spec 101): the env could name exactly ONE issuer and
needed a redeploy to change, while an instance realistically runs Google
alongside a corporate IdP — and the signup allowlist has to be editable at
runtime, since "let this domain in" is an everyday admin act, not a deploy.

`user_identities` is the reason a Google login lands on the AD account instead
of a duplicate. The FIRST login matches by verified email; the identity row it
writes pins the account to the IdP's immutable subject, so later logins survive
a mailbox rename and a recycled address can never inherit a leaver's account.
"""

import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from .types import SsoProviderSource


class SsoProvider(Base, TimestampMixin):
    """One configured identity provider. `client_secret` is stored as-is (it must
    be replayed on every token exchange — the webhook-secret/AI-key precedent);
    reads expose `has_client_secret` instead."""

    __tablename__ = "sso_providers"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))  # the login button's label
    kind: Mapped[str] = mapped_column(String(20))  # SsoKind
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)  # login-button order

    issuer: Mapped[str] = mapped_column(String(500), default="")  # "" = the kind's default
    client_id: Mapped[str] = mapped_column(String(500), default="")
    client_secret: Mapped[str] = mapped_column(Text, default="")
    scopes: Mapped[str] = mapped_column(String(500), default="")  # "" = the kind's default

    # --- signup policy --------------------------------------------------------
    # Whether a login with NO matching account may create one at all. Off = this
    # provider can only sign in people who already exist (however they got here).
    auto_provision: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    # Lowercased bare domains ("radd-hq.com") that may create a NEW account.
    # EMPTY = no signups — the strict reading of "signups are disabled except for
    # these domains", so a provider added without a list can't quietly let the
    # internet in. Existing accounts are unaffected: the list gates CREATION only.
    allowed_signup_domains: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    # An unverified email must never be trusted: both LINKING to an existing
    # account and creating a new one key off the address, so an IdP that lets a
    # user self-assert `email` would otherwise hand out other people's accounts.
    # On by default; an admin whose issuer omits the standard `email_verified`
    # claim can opt out deliberately rather than being silently insecure.
    require_verified_email: Mapped[bool] = mapped_column(
        Boolean, server_default=true(), default=True
    )

    # --- group → role sync ----------------------------------------------------
    group_claim: Mapped[str] = mapped_column(String(100), default="groups")
    # Comma-separated group names whose members become instance admins. EMPTY
    # means this provider carries no role opinion AT ALL and must leave
    # `instance_role` alone — otherwise a Google login (which ships no group
    # claim) would demote the AD admin it just linked to.
    admin_groups: Mapped[str] = mapped_column(String(1000), default="")

    source: Mapped[str] = mapped_column(String(10), default=SsoProviderSource.USER.value)

    @property
    def has_client_secret(self) -> bool:
        return bool(self.client_secret)


class SsoProviderDefaultGrant(Base, TimestampMixin):
    """One role a NEW account gets from this provider, at one scope (RADD-780).

    Deliberately the same shape as `global_role_grants` — (role, project_id
    NULL = global) — because these rows ARE the template the provisioner copies
    into that table. RADD-777 shipped a single `default_role_id` instead, which
    could say "everyone gets Member everywhere" and nothing else; a grant is
    (role, scope), and dropping the scope made the setting unable to express the
    thing it existed for.

    Real foreign keys, both CASCADE: a deleted role or project takes its
    template row with it. The alternative considered was a JSONB list on the
    provider, which stores ids nothing enforces — and a template that mints a
    grant to a role that no longer exists is a login-time failure caused by an
    admin tidying a list weeks earlier.

    Applied at account CREATION only and never reconciled; see
    `service.provision`. That property is what makes "this must never undo an
    admin's later change" free rather than enforced.
    """

    __tablename__ = "sso_provider_default_grants"
    __table_args__ = (
        UniqueConstraint(
            "provider_id", "role_id", "project_id", name="uq_sso_default_grant"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sso_providers.id", ondelete="CASCADE"), index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))
    #: NULL = granted instance-wide, exactly as in `global_role_grants`.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )


class SsoProviderDefaultTeam(Base, TimestampMixin):
    """A team a NEW account from this provider joins (RADD-781).

    Sibling of `SsoProviderDefaultGrant` and deliberately a separate table: a
    team membership is not a (role, scope) pair, and folding both into one row
    shape would mean a nullable column that is meaningful for exactly half the
    rows.

    Only LOCAL teams belong here. A directory-linked team's membership is owned
    by the AD group (spec 87 — `ensure_membership_editable` answers 409), so a
    template pointing at one could only ever fail at login. The provisioner
    skips those rather than letting a stale template break a sign-in.
    """

    __tablename__ = "sso_provider_default_teams"
    __table_args__ = (UniqueConstraint("provider_id", "team_id", name="uq_sso_default_team"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sso_providers.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))


class UserIdentity(Base, TimestampMixin):
    """A (provider, subject) pair bound to a local account.

    `subject` is the IdP's `sub` claim — immutable and unique within the issuer,
    which is exactly what email is not. One user may hold several identities
    (Google + Okta + their AD login all resolving to one person)."""

    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("provider_id", "subject"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sso_providers.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str] = mapped_column(String(255))
    # The email this identity last presented — diagnostics only. Never matched
    # on after the first login (that is the whole point of pinning to `subject`).
    email: Mapped[str] = mapped_column(String(320), default="")
    claims: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
