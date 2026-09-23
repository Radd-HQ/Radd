import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

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
    """One person, as everyone with an account may see them (RADD-769).

    The narrow half of a directory split by AUDIENCE. `UserRead` carries `email`,
    `source`, `instance_role` and `last_login_at` — administrative facts, and the
    reason `GET /users` is gated on `user.manage`. But naming a colleague is not
    an administrative act: assigning work, `@`-mentioning someone and rendering
    "edited by" all need a list of who exists, and gating those behind
    `user.manage` meant an ordinary member met a 403 on nearly every issue and
    page they opened.

    What is left is what a picker draws: who they are, what to render, and
    whether they are still around. Email is deliberately absent — it was the
    pickers' disambiguator, and keeping it would have published every address in
    the instance to every account in it, which is a larger change than the bug
    it fixes.

    Service accounts (spec 113) are NOT filtered out. They cannot log in, but
    they can author a page version or a comment, and a directory that omits them
    would leave those bylines unresolvable — a hole in the read path in exchange
    for tidier pickers, which already filter on `active`.

    `source` IS here (RADD-869): without it a picker rendered a service account
    exactly like a colleague, which contradicted the "never mistaken for a
    person" intent. Which auth backend a person uses is not an administrative
    secret the way their address is; the SPA badges `service` rows.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    active: bool
    source: str
    avatar_color: str | None = None
    avatar_emoji: str | None = None
    avatar_url: str | None = None  # RADD-1295: see User.avatar_url
    #: RADD-938 — only when the caller passed `project_id`: does this person hold
    #: item.read on THAT project through a grant? `None` means the question was
    #: not asked, which is different from "no" and must not render as a warning.
    has_access: bool | None = None
    #: RADD-1034 — true when this row is an email-provisioned account
    #: (`UserSource.EMAIL`), returned only when the caller asked for them via
    #: `include_requesters=true`. This is narrower than exposing `source`
    #: itself (already present, RADD-869, so pickers can badge `service` rows):
    #: `source` names WHICH backend authenticated someone, a fact this class's
    #: own docstring argues is not a picker's business beyond "service or not".
    #: `external` answers a DIFFERENT, narrower question — "is this a stranger
    #: who emailed the desk, not a colleague" — without handing the SPA the
    #: `email` sentinel to hardcode; today that question happens to reduce to
    #: `source == "email"`, but the field keeps that mapping server-side so a
    #: second requester-like source wouldn't need an SPA change.
    external: bool = False


class PermissionSourceRead(BaseModel):
    """One atom the user holds, and where it came from (RADD-779).

    `kind` is `baseline` | `role` | `instance-admin`. The admin case answers a
    single row with `permission="*"`: an instance admin holds everything BECAUSE
    they are an admin, and enumerating ninety atoms as though each were granted
    would hide the one fact that matters.
    """

    permission: str
    kind: str
    role_name: str | None = None
    #: RADD-809 — backlink to the supplying role (the Baseline row for kind
    #: "baseline"), the channel it arrived through, and its scope.
    role_id: uuid.UUID | None = None
    scope: str = "global"  # global | project | space
    via: str | None = None  # membership | team | grant | attached | group
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
    """Effective answers, as COUNTS (RADD-809 — guard-level conclusions are
    workflow-data-dependent and out of scope).

    RADD-933 split the read count in two. `readable_projects` counted with
    `holds_base`, which is right for a GATE — `item.read@own` genuinely holds
    `item.read` in qualified form (RADD-823) — and wrong for a SUMMARY: an
    account holding nothing but the Baseline's `item.read@own` was reported as
    reading items in all 97 projects, which an admin reads as "sees
    everything". What was true is "can read their OWN items there", and for an
    account that has never logged in that is no items at all.

    So: `readable_projects` is now the UNQUALIFIED count, and
    `own_readable_projects` is the remainder reachable only through a qualifier.
    Dropping the qualified projects entirely was rejected — `item.read@own` is
    real access to real rows, and an admin auditing a leaver needs to see it.
    The fault was conflation, not inclusion.
    """

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
    """A team or directory group the person belongs to, and what it confers
    (RADD-933).

    The Users page could list a person's DIRECT grants and their resulting
    atoms, but not the carriers in between — so "why can they see this?" had no
    answer on the page, and a team that confers nothing today (the common case)
    was invisible even though it is exactly the row that explains tomorrow's
    change when someone grants a role to it.
    """

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
    #: Spec 121: the request carried no credential and is acting as the Anyone
    #: principal. The SPA keys everything personal (inbox, pins, realtime,
    #: preferences) on this being False; `id` is the principal's fixed id.
    anonymous: bool = False
    #: Set while this session previews another account (RADD-836 U1) — the rest
    #: of the payload describes the TARGET, which is the point.
    view_as: ViewAsRead | None = None
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
    #: RADD-843 — area-visibility facts the client cannot derive from lists it
    #: already loads, keyed by the contributing plugin's `NavFactSpec.key`
    #: (RADD-892). An open map rather than named booleans because auth does not
    #: know which features exist; a MISSING key means visible, which is how the
    #: SPA already reads an unknown fact.
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


# --- roles as data (spec 06) ---

RoleKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")]


def _validate_atoms(values: list[str] | None) -> list[str] | None:
    """Atoms are strings now (spec 93/A2) — builtin OR plugin-registered. Validate
    membership in the live catalog so a garbage atom is still rejected (the
    guarantee the `list[Permission]` enum used to give), while plugin atoms pass.

    RADD-823: an atom may carry a relation qualifier (`item.update@team`). The
    BASE must be in the catalog and the relation must be REGISTERED for the
    atom's relation DOMAIN — its own resource, unless the owning module
    declared a parent domain (RADD-844: `comment.write` qualifies against the
    ITEM the comment lands on). An unregistered qualifier would be stored,
    resolve to nothing, and read as a mysterious denial."""
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
    group_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_subject(self) -> "GlobalGrantEntry":
        named = [x for x in (self.user_id, self.team_id, self.group_id) if x is not None]
        if len(named) != 1:
            raise ValueError("exactly one of user_id/team_id/group_id is required")
        return self


class GlobalGrantsUpdate(BaseModel):
    """PUT /roles/{id}/global-grants — the FULL set of people and teams that
    hold this role instance-wide, replaced atomically."""

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
    """POST /role-grants — the unified Grant Role dialog (spec 91 → RADD-791).

    Grant a role to a user OR team: instance-wide (both id lists empty), or on
    any number of projects, or any number of wiki spaces. ONE dialog covers every
    scope; growing a second one for spaces is how two scopes drift into two sets
    of rules.
    """

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
    """One qualifier an atom may carry (RADD-939): `own`, `team`, `participant`…

    `label` is the relation's own prose ("they reported", "shared with them"),
    written to complete the sentence the matrix draws — the role grants this
    verb for items *they reported*.
    """

    key: str
    label: str


class PermissionRead(BaseModel):
    """One row of the GET /permissions catalog (feeds the admin matrix UI)."""

    key: str  # spec 93/A2: builtin atom OR plugin-registered
    description: str
    scope: PermissionScope
    resource: str  # spec 50: the resource half of the key (item, state, …) — matrix grouping
    action: str  # spec 50: the verb half (create/read/update/delete/manage/…) — matrix column
    #: RADD-939: the relation qualifiers this atom may carry, so the matrix can
    #: draw `item.read@own` instead of rendering it as nothing. Resolved through
    #: the atom's relation DOMAIN — the same lookup `_validate_atoms` uses to
    #: accept a write, deliberately: a catalog that offered a combination the
    #: validator rejects (or hid one it accepts) would be a second opinion about
    #: one rule, and the two would drift.
    relations: list[RelationOptionRead] = []


class BaselinePreflightRequest(BaseModel):
    """The Baseline as the admin is ABOUT to store it."""

    permissions: list[str] = Field(default_factory=list)

    @field_validator("permissions")
    @classmethod
    def _known_atoms(cls, v: list[str]) -> list[str]:
        return _validate_atoms(v) or []


class BaselinePreflightRow(BaseModel):
    """One affected person: what they lose globally, and where item read
    survives via a project-scoped source (membership, team, scoped grant)."""

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
