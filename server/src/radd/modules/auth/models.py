import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from .types import InstanceRole, UserSource


class User(Base, TimestampMixin):
    __tablename__ = "users"

    #: Spec 113 — the scope of the API key this request authenticated with, set by
    #: `service.user_for_api_token` and read by `authz.effective_permissions`. NOT a
    #: column: it belongs to the request's principal, not to the account. None means
    #: unscoped (a session cookie, a personal token, or an internal actor).
    token_scope = None

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lowercase
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(String(255))  # None = SSO-only (future)
    instance_role: Mapped[str] = mapped_column(String(20), default=InstanceRole.MEMBER)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Spec 84: which auth system created the account (UserSource). Creation
    # points set it explicitly (ldap/sso provision override the local default);
    # the migration backfilled local/unknown from password_hash.
    source: Mapped[str] = mapped_column(
        String(20), default=UserSource.LOCAL, server_default=UserSource.UNKNOWN.value
    )
    # Stamped in create_session — sessions are only minted by the three login
    # paths (local/TOTP, LDAP, OIDC), so one seam covers them all (spec 84).
    last_login_at: Mapped[datetime | None] = mapped_column()
    # Personal profile (spec 34). Avatar = colored circle with initials, or an
    # emoji override; timezone is an IANA name ("" = use the browser's).
    avatar_color: Mapped[str | None] = mapped_column(String(7))
    avatar_emoji: Mapped[str | None] = mapped_column(String(16))
    timezone: Mapped[str] = mapped_column(String(64), default="", server_default="")
    # Generic per-user preferences (spec 94) — a JSON dict any plugin/feature can stash small,
    # cross-browser per-user prefs in (e.g. which plugin contributions the user disabled).
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class UserTotp(Base, TimestampMixin):
    """TOTP enrollment (spec 48). A row with confirmed_at NULL is a pending
    setup (secret shown once, not yet verified); confirmed = MFA enforced on
    password login. SSO/LDAP logins are untouched — the IdP owns MFA there."""

    __tablename__ = "user_totp"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    secret: Mapped[str] = mapped_column(String(64))  # base32
    confirmed_at: Mapped[datetime | None] = mapped_column()


class UserSession(Base):
    """Browser session. The cookie carries the raw token; only its sha256 is stored."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 hex
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ApiToken(Base):
    """Personal access token (`radd_pat_…`). Raw value returned once; only the hash stored."""

    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 hex
    prefix_display: Mapped[str] = mapped_column(String(12))  # first chars, for the UI
    #: Spec 113 — raw permission atoms narrowing what this key may do:
    #: {"global": [atoms], "projects": {uuid: [atoms]}}. NULL = unscoped = the
    #: account's full authority, which is what every pre-113 token carries.
    scopes: Mapped[dict | None] = mapped_column(JSONB, default=None)
    expires_at: Mapped[datetime | None]
    last_used_at: Mapped[datetime | None]  # write throttled; see service.user_for_api_token
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Role(Base, TimestampMixin):
    """A named permission set (spec 06). Builtins (admin/member/viewer) are seeded
    globally and immutable; custom roles carry any subset of Permission values."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(100))  # slug, globally unique
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(500), default="")
    permissions: Mapped[list[str]] = mapped_column(JSONB, default=list)  # Permission values
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)


class GlobalRoleGrant(Base, TimestampMixin):
    """A SCOPEABLE role grant (spec 87 → spec 91): a role held by a user or a team,
    either instance-wide (`project_id` NULL = global, the spec-87 behavior) or on
    one project (`project_id` set). Exactly one of user_id/team_id.

    This is the DELIVERY MECHANISM for permission atoms outside project membership.
    Global grants apply at BOTH scopes (global checks union them in; every project
    treats them as one more granted role). A project-scoped grant applies only on
    that project — the "grant any role at global or project scope" the unified Grant
    Role dialog writes, so a team can be given a role on specific projects without
    project membership.

    Rows die with the user/team/project (FK CASCADE); the role is RESTRICTed while
    any grant references it, matching project_members/project_teams.
    """

    __tablename__ = "global_role_grants"
    __table_args__ = (
        # project_id in the key so the same role can be held globally AND per-project;
        # NULLs are distinct in Postgres, so duplicate GLOBAL grants are guarded in code.
        UniqueConstraint("role_id", "user_id", "project_id"),
        UniqueConstraint("role_id", "team_id", "project_id"),
        CheckConstraint("(user_id IS NULL) <> (team_id IS NULL)", name="one_subject"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    # NULL = global (every project); set = scoped to that project only.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )


class ProjectMember(Base):
    """Direct user → project role assignment (complements team-granted roles)."""

    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"))  # RESTRICT on delete
