import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from .types import DuplicateKind, InstanceRole, Permission, PermissionScope, UserSource
from radd.apitypes import UtcDatetime

# Deliberately loose — deliverability is the mail server's problem. Normalized to lowercase.
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_lower=True, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    ),
]


class LoginRequest(BaseModel):
    email: Email
    password: str = Field(max_length=200)


# TOTP / MFA (spec 48)


class TotpLoginRequest(LoginRequest):
    code: str = Field(min_length=6, max_length=10)


class TotpSetupRead(BaseModel):
    secret: str  # shown once; user pastes into an authenticator app
    otpauth_uri: str


class TotpCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class TotpStatusRead(BaseModel):
    enabled: bool
    pending: bool  # setup created, not yet confirmed


class UserMergeRequest(BaseModel):
    """POST /users/{id}/merge — fold the path user (the duplicate) into this one."""

    into_user_id: uuid.UUID


class UserCreate(BaseModel):
    email: Email
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    instance_role: InstanceRole = InstanceRole.MEMBER


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    instance_role: InstanceRole
    active: bool
    avatar_color: str | None = None
    avatar_emoji: str | None = None
    timezone: str = ""
    # Spec 84 user administration: where the account came from + last sign-in.
    source: UserSource = UserSource.UNKNOWN
    last_login_at: UtcDatetime | None = None


class UserAdminUpdate(BaseModel):
    """PATCH /users/{id} (specs 84/86, instance admin): rename, activate/
    deactivate, and set instance_role (admin|member — the only role ladder
    since spec 86; self-demotion is a 409). Deactivation revokes the user's
    sessions and blocks every login path."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    active: bool | None = None
    instance_role: InstanceRole | None = None


class UserContentSummary(BaseModel):
    """What an account owns (spec 89) — drives the delete dialog. Everything here
    moves to the successor EXCEPT `worklogs`, which are discarded: crediting
    someone with hours they never worked would corrupt every time report."""

    reported_items: int = 0
    assigned_items: int = 0
    comments: int = 0
    documents: int = 0
    views: int = 0
    dashboards: int = 0
    owned_teams: int = 0
    attachments: int = 0
    approvals: int = 0
    worklogs: int = 0
    worklog_seconds: int = 0


class DuplicateUserGroup(BaseModel):
    """One candidate group from GET /users/duplicates (spec 84) — a heuristic
    feed for the merge UI, never auto-merged. Inactive accounts are included
    (each row carries `active`)."""

    kind: DuplicateKind
    key: str  # the shared normalized value (email local part or lowered name)
    users: list[UserRead]


class MeRead(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    instance_role: InstanceRole
    # Spec 86 stage 3: the global role + global-scope permission union, flat —
    # the synthetic `workspaces` wrapper is gone.
    global_role: InstanceRole
    # spec 93/A2: atoms are strings (builtin ∪ plugin-registered) — admin's union
    # includes plugin atoms, which aren't enum members.
    permissions: list[str] = Field(default_factory=list)
    # Spec 87: does this person own or manage at least one team? A team leader
    # holds no global team atom, so the permission union above cannot answer it —
    # and without it the SPA would hide the Teams page from the very people the
    # delegation exists for.
    manages_teams: bool = False
    avatar_color: str | None = None
    avatar_emoji: str | None = None
    timezone: str = ""


class ProfileUpdate(BaseModel):
    """PATCH /auth/me (spec 34) — omitted = unchanged; explicit null clears avatar."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    avatar_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    avatar_emoji: str | None = Field(default=None, max_length=16)
    timezone: str | None = Field(default=None, max_length=64)


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    expires_at: UtcDatetime | None = None
    #: Spec 113 — raw permission atoms narrowing this key below its account:
    #: {"global": [atoms], "projects": {uuid: [atoms]}}. Omitted/None = unscoped,
    #: which is what every personal token has always been.
    scopes: dict | None = None


class TokenCreated(BaseModel):
    token: str  # full token — shown exactly once
    id: uuid.UUID
    name: str
    prefix_display: str
    expires_at: UtcDatetime | None
    scopes: dict | None = None


class TokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix_display: str
    expires_at: UtcDatetime | None
    last_used_at: UtcDatetime | None
    created_at: UtcDatetime
    scopes: dict | None = None  # spec 113 — null means unscoped


# --- service accounts (spec 113) ---


class ServiceAccountCreate(BaseModel):
    """A service account is a user that cannot log in. The email is synthetic and
    generated from the name unless one is given, because nobody reads it."""

    name: str = Field(min_length=1, max_length=200)
    email: Email | None = None
    description: str = Field(default="", max_length=500)


class ServiceAccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    active: bool | None = None


class ServiceAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    active: bool
    created_at: UtcDatetime
    token_count: int = 0


# --- roles as data (spec 06) ---

RoleKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")]


def _validate_atoms(values: list[str] | None) -> list[str] | None:
    """Atoms are strings now (spec 93/A2) — builtin OR plugin-registered. Validate
    membership in the live catalog so a garbage atom is still rejected (the
    guarantee the `list[Permission]` enum used to give), while plugin atoms pass."""
    if values is None:
        return None
    from .types import all_permission_keys

    known = all_permission_keys()
    unknown = [v for v in values if v not in known]
    if unknown:
        raise ValueError(f"unknown permission atoms: {sorted(unknown)}")
    return values


class RoleCreate(BaseModel):
    key: RoleKey
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    permissions: list[str] = Field(default_factory=list)
    position: int | None = None  # default: appended after the last role

    @field_validator("permissions")
    @classmethod
    def _known_atoms(cls, v: list[str]) -> list[str]:
        return _validate_atoms(v) or []


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = None  # builtin roles reject this (409)
    position: int | None = None

    @field_validator("permissions")
    @classmethod
    def _known_atoms(cls, v: list[str] | None) -> list[str] | None:
        return _validate_atoms(v)


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    description: str
    permissions: list[str]  # spec 93/A2: atoms are strings (builtin ∪ plugin-registered)
    is_builtin: bool
    position: int
    created_at: UtcDatetime


class GlobalGrantEntry(BaseModel):
    """One instance-wide role grant to write (spec 87): exactly one of
    user_id/team_id."""

    user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_subject(self) -> "GlobalGrantEntry":
        if (self.user_id is None) == (self.team_id is None):
            raise ValueError("exactly one of user_id/team_id is required")
        return self


class GlobalGrantsUpdate(BaseModel):
    """PUT /roles/{id}/global-grants — the FULL set of people and teams that
    hold this role instance-wide, replaced atomically."""

    grants: list[GlobalGrantEntry] = Field(default_factory=list, max_length=100)


class GlobalGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role_id: uuid.UUID
    user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    # NULL = global; set = scoped to that project (spec 91).
    project_id: uuid.UUID | None = None


class RoleGrantCreate(BaseModel):
    """POST /role-grants — the unified Grant Role dialog (spec 91). Grant a role to a
    user OR team, at global scope (empty project_ids) or to one/more projects."""

    role_id: uuid.UUID
    user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    # Empty = a single GLOBAL grant; each id = one project-scoped grant.
    project_ids: list[uuid.UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_subject(self) -> "RoleGrantCreate":
        if (self.user_id is None) == (self.team_id is None):
            raise ValueError("exactly one of user_id/team_id is required")
        self.project_ids = list(dict.fromkeys(self.project_ids))
        return self


class PermissionRead(BaseModel):
    """One row of the GET /permissions catalog (feeds the admin matrix UI)."""

    key: str  # spec 93/A2: builtin atom OR plugin-registered
    description: str
    scope: PermissionScope
    resource: str  # spec 50: the resource half of the key (item, state, …) — matrix grouping
    action: str  # spec 50: the verb half (create/read/update/delete/manage/…) — matrix column


class ProjectMemberUpsert(BaseModel):
    user_id: uuid.UUID
    role_id: uuid.UUID


class ProjectMemberRoleUpdate(BaseModel):
    role_id: uuid.UUID


class ProjectMemberRead(BaseModel):
    project_id: uuid.UUID
    user_id: uuid.UUID
    role_id: uuid.UUID
    role: str  # the role's key, hydrated for display
