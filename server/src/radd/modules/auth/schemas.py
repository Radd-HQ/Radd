import uuid
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .types import DuplicateKind, InstanceRole, PermissionScope, UserSource
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
    recovery_codes_remaining: int  # unused single-use fallbacks (RADD-677)


class TotpRecoveryCodesRead(BaseModel):
    """Shown ONCE — only hashes are stored."""

    recovery_codes: list[str]


class MfaEnrollmentTicketRequest(BaseModel):
    """RADD-1279: the ticket a login refused under `require_mfa` received."""

    ticket: str = Field(min_length=16, max_length=200)


class MfaEnrollmentConfirm(MfaEnrollmentTicketRequest):
    code: str = Field(min_length=6, max_length=10)


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
    avatar_url: str | None = None  # RADD-1295: see User.avatar_url
    timezone: str = ""
    # Spec 84 user administration: where the account came from + last sign-in.
    source: UserSource
    last_login_at: UtcDatetime | None = None
    # RADD-1279: holds a CONFIRMED TOTP enrolment. Filled by the router in one
    # query per page (`mfa_policy.enrolled_ids`), never per row.
    mfa_enabled: bool = False


class UserDirectoryEntry(BaseModel):
    """One person as every signed-in user may see them (RADD-769): what a picker
    draws, never administrative facts. No email — it would publish every address
    to every account. Service accounts stay in (they author bylines); `source` is
    here so pickers can badge them (RADD-869)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    active: bool
    source: str
    avatar_color: str | None = None
    avatar_emoji: str | None = None
    avatar_url: str | None = None  # RADD-1295: see User.avatar_url
    #: RADD-938: only when the caller passed `project_id` — does this person hold
    #: item.read there through a grant? None = not asked, not "no".
    has_access: bool | None = None
    #: RADD-1034: an email-provisioned requester (returned only on request).
    external: bool = False


class PermissionSourceRead(BaseModel):
    """One atom the user holds and where it came from (RADD-779); `kind` is
    baseline | role | instance-admin, and an admin answers ONE `"*"` row."""

    permission: str
    kind: str
    role_name: str | None = None
    #: RADD-809 — backlink to the supplying role (the Baseline row for kind
    #: "baseline"), the channel it arrived through, and its scope.
    role_id: uuid.UUID | None = None
    scope: str = "global"  # global | project | space
    via: str | None = None  # grant | team | group
    via_team: str | None = None
    #: RADD-833: the carrying group + the nesting chain (granted → direct).
    via_group: str | None = None
    group_path: list[str] | None = None
    scope_label: str | None = None  # project key / space name (team view rows)
    #: Held via an umbrella (project.manage implies state.create), not granted
    #: directly — so the inspector never claims a role's checkbox was ticked.
    implied: bool = False


class ResourceAccessRowRead(BaseModel):
    """One spec-92 grant row reaching the inspected subject (RADD-809)."""

    resource_type: str
    resource_id: str
    resource_label: str | None = None
    access: str
    effect: str = "allow"  # RADD-819: a deny row names what killed the access
    subject_type: str  # user | team | role
    subject_id: uuid.UUID
    subject_name: str | None = None  # team/role name; None = the user directly
    project_id: uuid.UUID | None = None
    project_key: str | None = None
    #: RADD-820: provenance an access review actually needs on the row.
    granted_by_name: str | None = None
    expires_at: UtcDatetime | None = None


class ResourceTypeAccessRead(BaseModel):
    """Grants per registered resource type, with the default the reader needs
    to interpret an empty list: default-open types are reachable with no rows."""

    resource_type: str
    label: str
    default_open: bool
    hierarchical: bool
    accesses: list[str]
    rows: list[ResourceAccessRowRead]


class AccessSummaryRead(BaseModel):
    """Effective reach as COUNTS (RADD-809). `readable_projects` counts
    UNQUALIFIED item.read; `own_readable_projects` the projects reachable only
    through a qualifier (@own/@participant) — `holds_base` is right for a gate and
    wrong for a summary (RADD-933)."""

    readable_projects: int
    #: Projects where the atom is held ONLY in qualified form (own/participant/…).
    own_readable_projects: int = 0
    updatable_projects: int
    own_updatable_projects: int = 0
    total_projects: int
    readable_spaces: int | None = None  # None = pages module not installed
    total_spaces: int | None = None


class CarrierGrantRead(BaseModel):
    """One role a carrier confers, and where."""

    role_name: str
    scope: str  # "global" | "project" | "space"
    scope_label: str | None = None


class MembershipRead(BaseModel):
    """A team or directory group the person belongs to, and what it confers (RADD-933)."""

    kind: str  # "team" | "group"
    id: uuid.UUID
    name: str
    #: Groups only: the nesting chain from the granted group down to the member.
    path: list[str] | None = None
    confers: list[CarrierGrantRead] = []


class UserAccessRead(BaseModel):
    """The resource half of the inspector plus the summary counts (the atom
    half stays on /users/{id}/permissions)."""

    resources: list[ResourceTypeAccessRead]
    summary: AccessSummaryRead
    #: RADD-933 — the carriers between "granted to" and "held by".
    memberships: list[MembershipRead] = []


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
    moves to the successor EXCEPT `worklogs`, which are discarded (crediting
    someone with hours they never worked would corrupt every time report), and
    `owned_teams`, which go ownerless (RADD-784: running a team is delegation,
    not content — a new owner is chosen deliberately, never inherited)."""

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


class SuccessorGap(BaseModel):
    """One scope where a successor candidate holds less than the account being
    deleted (RADD-784)."""

    scope_type: str  # "instance" | "global" | "project" | "space"
    label: str  # project KEY, or "global" / "instance" / "wiki space"
    scope_id: uuid.UUID | None = None
    missing: list[str]


class SuccessorCheck(BaseModel):
    """RADD-784: is this candidate viable? Access never transfers on delete, so
    the successor must already hold at least what the account holds — `gaps`
    names exactly what is missing, per scope, so the admin can grant it
    deliberately or pick someone else."""

    viable: bool
    gaps: list[SuccessorGap]


class DuplicateUserGroup(BaseModel):
    """One candidate group from GET /users/duplicates (spec 84) — a heuristic
    feed for the merge UI, never auto-merged. Inactive accounts are included
    (each row carries `active`)."""

    kind: DuplicateKind
    key: str  # the shared normalized value (email local part or lowered name)
    users: list[UserRead]


class ViewAsRead(BaseModel):
    """The banner's facts while an admin previews another account (RADD-836 U1)."""

    real_id: uuid.UUID
    real_name: str


class ViewAsStart(BaseModel):
    user_id: uuid.UUID


class MeRead(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    instance_role: InstanceRole
    #: Spec 121: no credential — acting as the Anyone principal (`id` is its fixed id).
    anonymous: bool = False
    #: Set while previewing another account (RADD-836); the payload describes the TARGET.
    view_as: ViewAsRead | None = None
    global_role: InstanceRole
    permissions: list[str] = Field(default_factory=list)  # the global-scope union
    # Spec 87: owns/manages a team — a leader holds no global team atom, so the
    # permission union cannot answer it.
    manages_teams: bool = False
    #: RADD-843/892: area-visibility facts by NavFactSpec.key; a MISSING key means visible.
    nav: dict[str, bool] = Field(default_factory=dict)
    avatar_color: str | None = None
    avatar_emoji: str | None = None
    avatar_url: str | None = None  # RADD-1295: see User.avatar_url
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


class ServiceKeySummaryRead(BaseModel):
    id: uuid.UUID
    name: str
    prefix_display: str
    expires_at: UtcDatetime | None
    last_used_at: UtcDatetime | None
    created_at: UtcDatetime
    restricted: bool
    global_count: int
    project_count: int


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
    #: RADD-1499 — the Automation account: seeded, converged at startup, and never
    #: renamed, deactivated or deleted (the page says so instead of offering it).
    builtin: bool = False


# --- roles as data (spec 06) ---

RoleKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")]


def _validate_atoms(values: list[str] | None) -> list[str] | None:
    """Validate atoms (builtin or plugin-registered) against the live catalog. A
    relation qualifier (RADD-823) must be REGISTERED for the atom's relation
    DOMAIN (RADD-844: `comment.write` qualifies against the ITEM) — an
    unregistered one would be stored and read as a mysterious denial."""
    if values is None:
        return None
    from radd.kernel import registries

    from .types import RELATION_ANY, all_permission_keys, split_permission

    known = all_permission_keys()
    unknown: list[str] = []
    for value in values:
        base, relation = split_permission(value)
        if base not in known:
            unknown.append(value)
            continue
        if relation != RELATION_ANY:
            resource = registries.relation_domain(base)
            if relation not in registries.relations_for(resource):
                raise ValueError(
                    f"'{value}': no relation '@{relation}' is registered for '{resource}'"
                )
    if unknown:
        raise ValueError(f"unknown permission atoms: {sorted(unknown)}")
    return values


#: A list of permission atoms, validated against the live catalog.
Atoms = Annotated[list[str], AfterValidator(_validate_atoms)]


class RoleCreate(BaseModel):
    key: RoleKey
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    permissions: Atoms = Field(default_factory=list)
    position: int | None = None  # default: appended after the last role


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    permissions: Atoms | None = None  # builtin roles reject this (409)
    position: int | None = None


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
    user_id/team_id/group_id."""

    user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_subject(self) -> "GlobalGrantEntry":
        named = [x for x in (self.user_id, self.team_id, self.group_id) if x is not None]
        if len(named) != 1:
            raise ValueError("exactly one of user_id/team_id/group_id is required")
        return self


class GlobalGrantsUpdate(BaseModel):
    """PUT /roles/{id}/global-grants — the FULL set of users, teams and groups
    that hold this role instance-wide, replaced atomically."""

    grants: list[GlobalGrantEntry] = Field(default_factory=list, max_length=100)
    expected_grant_ids: list[uuid.UUID] = Field(max_length=100)


class GlobalGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role_id: uuid.UUID
    user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    #: RADD-820: NULL = permanent. Who made the grant; NULL = pre-existing.
    expires_at: UtcDatetime | None = None
    granted_by: uuid.UUID | None = None
    # Both NULL = global; one set = scoped to that project (spec 91) or that
    # wiki space (RADD-791). Never both — see the `one_scope` CHECK.
    project_id: uuid.UUID | None = None
    space_id: uuid.UUID | None = None


class GrantDirectoryRead(GlobalGrantRead):
    """Names are nullable when the actor cannot read their owning catalog."""

    role_name: str | None = None
    scope_label: str | None = None


class SpaceGrantDirectoryRead(GlobalGrantRead):
    role_name: str | None = None
    subject_name: str | None = None
    subject_active: bool | None = None
    expired: bool = False


class RoleGrantRoleUpdate(BaseModel):
    """PATCH /role-grants/{id} (RADD-1103): swap WHICH role the grant confers;
    scope stays. member.update's first enforcement site."""

    role_id: uuid.UUID


class RoleGrantCreate(BaseModel):
    """POST /role-grants — one Grant Role dialog for every scope (spec 91,
    RADD-791): a user, team or group; instance-wide, or one grant per id."""

    role_id: uuid.UUID
    user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    #: RADD-820: optional expiry for every grant this request writes.
    expires_at: UtcDatetime | None = None
    # Both empty = a single GLOBAL grant; each id = one scoped grant.
    project_ids: list[uuid.UUID] = Field(default_factory=list)
    space_ids: list[uuid.UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_subject(self) -> "RoleGrantCreate":
        named = [x for x in (self.user_id, self.team_id, self.group_id) if x is not None]
        if len(named) != 1:
            raise ValueError("exactly one of user_id/team_id/group_id is required")
        self.project_ids = list(dict.fromkeys(self.project_ids))
        self.space_ids = list(dict.fromkeys(self.space_ids))
        return self


class RelationOptionRead(BaseModel):
    """One qualifier an atom may carry (RADD-939); `label` completes the matrix's
    sentence (items *they reported*)."""

    key: str
    label: str


class PermissionRead(BaseModel):
    """One row of the GET /permissions catalog (feeds the admin matrix UI)."""

    key: str  # spec 93/A2: builtin atom OR plugin-registered
    description: str
    scope: PermissionScope
    resource: str  # spec 50: the resource half of the key (item, state, …) — matrix grouping
    action: str  # spec 50: the verb half (create/read/update/delete/manage/…) — matrix column
    #: RADD-939: the qualifiers this atom may carry, resolved through the SAME
    #: relation domain `_validate_atoms` accepts writes against.
    relations: list[RelationOptionRead] = []


class BaselinePreflightRequest(BaseModel):
    """The Baseline as the admin is ABOUT to store it."""

    permissions: Atoms = Field(default_factory=list)


class BaselinePreflightRow(BaseModel):
    """One affected person: what they lose globally, and where item read
    survives through a project-scoped grant."""

    user_id: uuid.UUID
    name: str
    email: str
    lost: list[str]
    retained_project_keys: list[str]
    lost_project_count: int


class BaselinePreflightRead(BaseModel):
    """The consequence of editing the Baseline to `proposed`, computed through
    the real resolvers before anything is written."""

    proposed: list[str]
    narrowed: list[str]  # atoms whose base survives in a narrower @relation form
    removed: list[str]  # atoms with no surviving form
    users_affected: int
    projects_affected: int
    total_users_checked: int
    rows: list[BaselinePreflightRow]  # capped sample; counts are never capped
    truncated: bool
