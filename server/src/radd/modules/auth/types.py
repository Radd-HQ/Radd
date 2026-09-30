import uuid
from dataclasses import dataclass
from enum import StrEnum

# Wire-format constants (not tunables — changing them invalidates existing clients/tokens).
SESSION_COOKIE_NAME = "radd_session"
PAT_PREFIX = "radd_pat_"
PAT_PREFIX_DISPLAY_CHARS = 12  # how much of a token the UI may keep showing

#: The Automation account (RADD-1499): a REAL users row that integrations write as
#: and author-less automations run as — a built-in SERVICE account (key-only, no
#: login, no mail, badged in pickers) that is instance-admin so authz never blocks
#: it. Defined here, where users are defined, and imported by automations, notify
#: and the throttle; the migrations carry the uuid as a literal on purpose. NOT
#: the loop guard (that is `Event.automated`). `principals.BUILTIN_ROWS` seeds it.
SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000a70a70")
SYSTEM_ACTOR_EMAIL = "automation@radd.system"
SYSTEM_ACTOR_NAME = "Automation"


class InstanceRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class UserSource(StrEnum):
    """Where an account came from (spec 84). Every creation point sets it
    explicitly (RADD-895 migrated the last pre-84 `unknown` rows away)."""

    LOCAL = "local"  # password login (register/seed/POST /users)
    LDAP = "ldap"  # provisioned by a directory bind or AD import
    OIDC = "oidc"  # provisioned by the OIDC callback
    JIRA = "jira"  # placeholder provisioned by the Jira importer (spec 90 follow-up)
    SERVICE = "service"  # spec 113 — a service account; authenticates by API key ONLY
    EMAIL = "email"  # RADD-828 — provisioned by mail ingest; cannot log in until SSO claims it
    PRINCIPAL = "principal"  # spec 121 — Anyone / Signed-in users: a grant subject, never a person


#: Sources that are not a PERSON to list, pick, assign or mail. The email
#: requesters (RADD-1034) and the spec-121 principals share every exclusion;
#: service accounts are excluded case by case (a byline may need them).
NON_PERSON_SOURCES: tuple[UserSource, ...] = (UserSource.EMAIL, UserSource.PRINCIPAL)

#: Sources with no PERSON behind the credential (RADD-1499): key-only service
#: accounts — the built-in Automation account among them — and the grant
#: principals. What the ledger's People/System split and the mailer's "is there
#: a mailbox" read. Distinct from NON_PERSON_SOURCES: an email requester is a
#: person, just not one to pick.
MACHINE_SOURCES: tuple[UserSource, ...] = (UserSource.SERVICE, UserSource.PRINCIPAL)


class DuplicateKind(StrEnum):
    """Why GET /users/duplicates grouped some accounts together (spec 84)."""

    EMAIL_LOCAL_PART = "email_local_part"  # same lowercased local part before the @
    NAME = "name"  # same case-insensitive display name


class Permission(StrEnum):
    """Typed aliases for permission atoms, for call sites (RADD-890).

    The CATALOG is the kernel registry: each atom is declared by the module that
    enforces it. This enum survives because `PROJECT_PERMISSIONS` (and so the
    seeded Manager role) is computed at auth import time, before any manifest
    exists. `tests/test_permission_ownership.py` asserts enum == registry."""

    GLOBAL_MANAGE = "global.manage"  # global settings + administration
    PROJECT_CREATE = "project.create"
    PROJECT_MANAGE = "project.manage"  # states/fields/labels/webhooks/teams/members
    PROJECT_DELETE = "project.delete"  # RADD-1174: global on purpose — see permissions.py
    ITEM_READ = "item.read"
    ITEM_CREATE = "item.create"
    ITEM_UPDATE = "item.update"
    WORKLOG_WRITE = "worklog.write"  # project-scoped; log work + manage own worklogs (spec 22)
    TIMESHEET_VIEW = "timesheet.view"  # global-scoped; see others' timesheets (spec 22)
    COMMENT_WRITE = "comment.write"
    COMMENT_READ_INTERNAL = "comment.read_internal"
    FORM_MANAGE = "form.manage"  # project-scoped; create/edit/delete intake forms (spec 17)
    # RADD-1304: add/remove an issue's participants (declared by participants).
    PARTICIPANT_MANAGE = "participant.manage"
    USER_MANAGE = "user.manage"
    AUTOMATION_MANAGE = "automation.manage"  # manage automation rules — global scope (spec 15)
    # Build automations whose actions run as SOMEONE ELSE (spec 116); without it
    # an automation acts as its author.
    AUTOMATION_ACT_AS = "automation.act_as"
    SCRIPT_MANAGE = "script.manage"  # RADD-1269: the scripts plugin — global scope
    # Per-entity manage actions (spec 36).
    STATE_MANAGE = "state.manage"  # project workflow states
    FIELD_MANAGE = "field.manage"  # custom-field definitions + field access rules
    WEBHOOK_MANAGE = "webhook.manage"  # webhook endpoints (global)
    # Wiki (spec 43) — SPACE-scoped (RADD-791).
    PAGE_READ = "page.read"  # read page spaces/pages + doc search
    PAGE_WRITE = "page.write"  # create/edit/move/archive pages, link items
    PAGE_MANAGE = "page.manage"  # manage spaces, hard-delete + restore pages
    # Spec 50: every resource has independent C/U/D atoms; umbrellas imply them.
    ITEM_DELETE = "item.delete"  # hard-delete work items (was project.manage)
    COMMENT_DELETE = "comment.delete"  # delete others' comments (author deletes own)
    WORKLOG_DELETE = "worklog.delete"  # delete others' worklogs (author deletes own)
    PAGE_DELETE = "page.delete"  # hard-delete pages (rides page.manage)
    # RADD-790: attaching is its own authority — discussing an issue must not need item.update.
    ATTACHMENT_CREATE = "attachment.create"  # upload a file to something
    ATTACHMENT_DELETE = "attachment.delete"  # delete your OWN attachments
    # Project-scoped config C/U/D (state/field/release/form/view/project-access):
    STATE_CREATE = "state.create"
    STATE_UPDATE = "state.update"
    STATE_DELETE = "state.delete"
    FIELD_CREATE = "field.create"
    FIELD_UPDATE = "field.update"
    FIELD_DELETE = "field.delete"
    RELEASE_CREATE = "release.create"
    RELEASE_UPDATE = "release.update"
    RELEASE_DELETE = "release.delete"
    FORM_CREATE = "form.create"
    FORM_UPDATE = "form.update"
    FORM_DELETE = "form.delete"
    VIEW_CREATE = "view.create"
    VIEW_UPDATE = "view.update"
    VIEW_DELETE = "view.delete"
    MEMBER_CREATE = "member.create"  # grant project access (member/team attach)
    MEMBER_UPDATE = "member.update"  # change a grant's role
    MEMBER_DELETE = "member.delete"  # revoke project access
    # RADD-816: catalog reads — Baseline-seeded, and revocable.
    LABEL_READ = "label.read"
    CYCLE_READ = "cycle.read"
    CANNED_READ = "canned.read"
    TEAM_READ = "team.read"
    ROLE_READ = "role.read"
    CARD_PRESET_READ = "cardpreset.read"
    ISSUE_TYPE_CREATE = "issue_type.create"  # spec 51 — per-project issue types
    ISSUE_TYPE_UPDATE = "issue_type.update"
    ISSUE_TYPE_DELETE = "issue_type.delete"
    # Global-scoped config C/U/D (label/webhook/canned/automation/cycle/sla/team/role/user):
    LABEL_CREATE = "label.create"
    LABEL_UPDATE = "label.update"
    LABEL_DELETE = "label.delete"
    WEBHOOK_CREATE = "webhook.create"
    WEBHOOK_UPDATE = "webhook.update"
    WEBHOOK_DELETE = "webhook.delete"
    CANNED_CREATE = "canned.create"
    CANNED_UPDATE = "canned.update"
    CANNED_DELETE = "canned.delete"
    CARD_PRESET_CREATE = "cardpreset.create"
    CARD_PRESET_UPDATE = "cardpreset.update"
    CARD_PRESET_DELETE = "cardpreset.delete"
    # Spec 113 — service accounts (principals that authenticate by API key only).
    SERVICE_ACCOUNT_CREATE = "service_account.create"
    SERVICE_ACCOUNT_UPDATE = "service_account.update"
    # Spec 111 — version-control connections (Forgejo/Gitea hosts + repos).
    VCSCONN_CREATE = "vcsconn.create"
    VCSCONN_UPDATE = "vcsconn.update"
    VCSCONN_DELETE = "vcsconn.delete"
    # RADD-1317 — Alertmanager receivers (rows since the env token became seed-only).
    ALERT_RECEIVER_CREATE = "alertreceiver.create"
    ALERT_RECEIVER_READ = "alertreceiver.read"
    ALERT_RECEIVER_UPDATE = "alertreceiver.update"
    ALERT_RECEIVER_DELETE = "alertreceiver.delete"
    AUTOMATION_CREATE = "automation.create"
    AUTOMATION_UPDATE = "automation.update"
    AUTOMATION_DELETE = "automation.delete"
    CYCLE_CREATE = "cycle.create"
    CYCLE_UPDATE = "cycle.update"
    CYCLE_DELETE = "cycle.delete"
    SLA_CREATE = "sla.create"
    SLA_UPDATE = "sla.update"
    SLA_DELETE = "sla.delete"
    TEAM_CREATE = "team.create"
    TEAM_UPDATE = "team.update"
    TEAM_DELETE = "team.delete"
    ROLE_CREATE = "role.create"
    ROLE_UPDATE = "role.update"
    ROLE_DELETE = "role.delete"
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    # Spec 89: hard delete, gated on reassigning the account's work.
    USER_DELETE = "user.delete"
    # Spec 75: dashboard.create also gates global_access; update/delete only
    # narrow API keys (ownership decides the rest).
    DASHBOARD_CREATE = "dashboard.create"
    DASHBOARD_UPDATE = "dashboard.update"
    DASHBOARD_DELETE = "dashboard.delete"


class CrudAction(StrEnum):
    """The four verbs of the resource × action matrix (spec 50)."""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"


class PermissionScope(StrEnum):
    """Where an atom is checked; containment is global ⊃ {project | space}."""

    PROJECT = "project"
    GLOBAL = "global"
    #: RADD-791 — checked against a WIKI SPACE, a scope the way a project is.
    SPACE = "space"


class GrantScopeKind(StrEnum):
    """What a role grant can be scoped TO (RADD-791); no scope = instance-wide.
    Typed FK columns (`project_id`, `space_id`) rather than a polymorphic pair, so
    the permission table keeps referential integrity."""

    PROJECT = "project"
    SPACE = "space"


# --- scope: the ONE fact auth must know at import time (RADD-890) -------------
# `PROJECT_PERMISSIONS` (and so the Manager role) is computed before any manifest
# exists; `tests/test_permission_ownership.py` checks this copy against the owners.

#: Atoms checked against a PROJECT.
_PROJECT_SCOPED: frozenset[str] = frozenset({
    "project.manage", "item.read", "item.create", "item.update", "worklog.write",
    "comment.write", "comment.read_internal", "form.manage", "state.manage", "field.manage",
    "item.delete", "comment.delete", "worklog.delete", "attachment.create",
    "attachment.delete", "state.create", "state.update", "state.delete", "field.create",
    "field.update", "field.delete", "release.create", "release.update", "release.delete",
    "form.create", "form.update", "form.delete", "view.create", "view.update", "view.delete",
    "member.create", "member.update", "member.delete", "issue_type.create",
    "issue_type.update", "issue_type.delete",
    # RADD-1303: SLA policies belong to a project (spec 67), so managing them
    # is a project right — held by the project's Manager via project.manage.
    "sla.create", "sla.update", "sla.delete",
    "participant.manage",  # RADD-1304
})

#: Atoms checked against a WIKI SPACE (RADD-791); an unscoped grant still applies everywhere.
_SPACE_SCOPED: frozenset[str] = frozenset({
    "page.read", "page.write", "page.manage", "page.delete",
})

#: Where each builtin atom is checked. GLOBAL is the default: an atom that is
#: not bound to a project or a space is instance-wide by construction.
PERMISSION_SCOPES: dict[Permission, PermissionScope] = {
    permission: (
        PermissionScope.PROJECT
        if permission.value in _PROJECT_SCOPED
        else PermissionScope.SPACE
        if permission.value in _SPACE_SCOPED
        else PermissionScope.GLOBAL
    )
    for permission in Permission
}


# Resources are declared by their plugins (RADD-890); this is the verb vocabulary.

_ACTION_VERB: dict[CrudAction, str] = {
    CrudAction.CREATE: "Create",
    CrudAction.READ: "See",
    CrudAction.UPDATE: "Edit",
    CrudAction.DELETE: "Delete",
}


def implied_map() -> dict[str, frozenset[str]]:
    """The umbrella→implied map, read LIVE from the kernel registry (a disabled
    plugin's umbrella stops expanding with it): a CrudResourceSpec's `manage`
    implies its `key.action` atoms; `PermissionSpec.implied_by` names umbrellas
    that expand to an atom; `.implies` covers relation-qualified forms
    (`item.update` -> `attachment.delete@own`)."""
    merged: dict[str, frozenset[str]] = {}

    def _add(umbrella: str, atoms: frozenset[str]) -> None:
        merged[umbrella] = merged.get(umbrella, frozenset()) | atoms

    from radd.kernel import registries

    for spec in registries.crud_resources.values():
        _add(spec.manage, frozenset(f"{spec.key}.{a}" for a in spec.actions))
    for atom in registries.permissions.values():
        for umbrella in atom.implied_by:
            _add(umbrella, frozenset({atom.key}))
        if atom.implies:
            _add(atom.key, frozenset(atom.implies))
    return merged


def expand_permissions(granted: "frozenset[Permission] | set[Permission] | set[str]") -> frozenset[str]:
    """Apply the umbrella→implied closure to a permission set, transitively (pure
    over strings — StrEnum atoms and plugin atom strings are interchangeable)."""
    result = {str(x) for x in granted}
    implied = implied_map()
    changed = True
    while changed:
        changed = False
        for umbrella, atoms in implied.items():
            if umbrella in result and not atoms <= result:
                result |= atoms
                changed = True
    return frozenset(result)


# Every project-scoped permission, in enum order (the Manager builtin's grant set).
PROJECT_PERMISSIONS: tuple[Permission, ...] = tuple(
    p for p in Permission if PERMISSION_SCOPES[p] is PermissionScope.PROJECT
)


def permission_parts(permission: "Permission | str") -> tuple[str, str]:
    """Decompose `item.delete` -> ("item", "delete") for the resource × action
    roles matrix (spec 50). The action is the whole suffix (e.g. read_internal).
    Accepts a plugin atom string as well as a builtin `Permission`; a relation
    qualifier (RADD-823) is stripped — the matrix cell is the base atom."""
    resource, _, action = base_permission(permission).partition(".")
    return resource, action


# --- relations (RADD-823): `resource.action@relation`; unqualified = `@any` ---
# A chain, widest first: any ⊃ team ⊃ own. What a relation MEANS for rows is the
# owning module's RelationSpec; this is pure string algebra.

RELATION_SEP = "@"

RELATION_ANY = "any"

#: The containment chain, outermost first. A relation not in this tuple is a
#: resource-specific extension and is treated as incomparable with the others
#: (contains only itself, plus `any` contains everything).
RELATION_ORDER: tuple[str, ...] = ("any", "team", "own")


def split_permission(key: "Permission | str") -> tuple[str, str]:
    """`item.update@team` -> ("item.update", "team"); unqualified -> `any`."""
    base, sep, relation = str(key).partition(RELATION_SEP)
    return base, (relation if sep else RELATION_ANY)


def base_permission(key: "Permission | str") -> str:
    return split_permission(key)[0]


def qualify_permission(base: str, relation: str) -> str:
    """The canonical spelling: `@any` is never written out."""
    return base if relation == RELATION_ANY else f"{base}{RELATION_SEP}{relation}"


def relation_contains(outer: str, inner: str) -> bool:
    """Does holding `outer` satisfy a need for `inner`? Chain containment:
    any ⊃ team ⊃ own; equal always; unknown relations only contain themselves."""
    if outer == inner or outer == RELATION_ANY:
        return True
    if outer in RELATION_ORDER and inner in RELATION_ORDER:
        return RELATION_ORDER.index(outer) <= RELATION_ORDER.index(inner)
    return False


def relation_meet(a: str, b: str) -> str | None:
    """The NARROWER of two relations (the lattice meet) — what a key scoped to
    one relation may do against an account holding another (spec 113 becomes
    lattice-aware here). None = incomparable: the pair grants nothing."""
    if relation_contains(a, b):
        return b
    if relation_contains(b, a):
        return a
    return None


def relations_held(
    permissions: "frozenset[Permission] | frozenset[str] | set[str]", base: "Permission | str"
) -> frozenset[str]:
    """The relation qualifiers a permission set holds for one base atom.
    `{"any"}`-containing = unrestricted; empty = the atom is not held at all.
    The set is not closed downward — callers test with `relation_contains`."""
    wanted = str(base)
    return frozenset(
        relation
        for atom in permissions
        for b, relation in (split_permission(atom),)
        if b == wanted
    )


# --- the catalog, composed LIVE from the kernel registry (RADD-890). The union
# with the enum keeps a DISABLED module's atoms addressable in stored roles. ---


def _registered_crud_atoms() -> dict[str, tuple["PermissionScope", str]]:
    """{atom: (scope, description)} for every registered CRUD resource's atoms + umbrella."""
    from radd.kernel import registries

    out: dict[str, tuple[PermissionScope, str]] = {}
    for spec in registries.crud_resources.values():
        scope = PermissionScope(spec.scope)
        out[spec.manage] = (scope, f"Manage {spec.label}.")
        for action in spec.actions:
            verb = _ACTION_VERB.get(CrudAction(action), action.capitalize())
            out[f"{spec.key}.{action}"] = (scope, f"{verb} {spec.label}.")
    return out


def _registered_atoms() -> dict[str, tuple["PermissionScope", str]]:
    """{key: (scope, description)} for every registered standalone atom. Merged
    AFTER the CRUD atoms so a bespoke umbrella sentence ("Create users and see
    the user directory") wins over the generated "Manage users."."""
    from radd.kernel import registries

    return {
        spec.key: (PermissionScope(spec.scope), spec.description)
        for spec in registries.permissions.values()
    }


def _all_registered() -> dict[str, tuple["PermissionScope", str]]:
    return {**_registered_crud_atoms(), **_registered_atoms()}


def all_permission_keys() -> frozenset[str]:
    """Every atom the system knows: the registry ∪ the typed alias enum."""
    return frozenset({p.value for p in Permission} | set(_all_registered()))


def permission_scope_of(key: "Permission | str") -> "PermissionScope":
    # A builtin atom answers from PERMISSION_SCOPES, else the registry. A relation
    # qualifier never changes WHERE an atom is checked (RADD-823): resolve the base.
    scope = PERMISSION_SCOPES.get(base_permission(key))  # type: ignore[arg-type]
    if scope is not None:
        return scope
    reg = _all_registered().get(base_permission(key))
    return reg[0] if reg else PermissionScope.GLOBAL


def permission_description_of(key: "Permission | str") -> str:
    """The owning module's sentence for this atom; "" once its plugin is
    disabled — the atom is still addressable in stored roles, but nothing is
    left to describe it."""
    reg = _all_registered().get(base_permission(key))
    return reg[1] if reg else ""


class BuiltinRoleKey(StrEnum):
    """Keys of the seeded builtin roles (immutable rows, except the Baseline's
    permission set)."""

    BASELINE = "baseline"  # RADD-773: what every active user holds; admin-editable
    MANAGER = "manager"
    MEMBER = "member"
    VIEWER = "viewer"
    #: RADD-828: an email-provisioned requester's floor INSTEAD of the Baseline, so
    #: mail ingest never hands strangers the staff policy row.
    REQUESTER = "requester"
    PUBLIC = "public"  # spec 121: granted to Anyone by the "Public project" switch
    CONTRIBUTOR = "contributor"  # spec 121: granted to Signed-in users by "contributions"


@dataclass(frozen=True)
class BuiltinRole:
    """Seed definition of a builtin role — the DB rows mirror these exactly (immutable)."""

    key: BuiltinRoleKey
    name: str
    description: str
    permissions: "tuple[Permission | str, ...]"
    position: int


#: RADD-1304 — what anyone may do on a ticket THEY reported, shared by the three
#: floors (Baseline, Requester, Contributor), which differ only in what they READ.
#: `@own` is the ITEM's relation for the writes, the row's AUTHOR for the deletes.
OWN_TICKET: tuple[str, ...] = (
    "comment.write@own",
    "attachment.create@own",
    "participant.manage@own",
    "comment.delete@own",
    "attachment.delete@own",
)

#: Shared into someone else's ticket (RADD-844): follow it and talk on it, like
#: a second reporter — but not reshape its roster.
SHARED_TICKET: tuple[str, ...] = (
    "comment.write@participant",
    "attachment.create@participant",
)

BUILTIN_ROLES: tuple[BuiltinRole, ...] = (
    BuiltinRole(
        key=BuiltinRoleKey.BASELINE,
        name="Baseline",
        description=(
            "What everyone with an account gets, on every project, without being "
            "granted anything. Edit this to widen or narrow the floor."
        ),
        # Read-only on purpose (RADD-773/825): item.read@own, not item.read —
        # grant wider reads through a role. @participant is the second-reporter
        # floor (RADD-844); OWN_TICKET/SHARED_TICKET are the shared own-ticket set
        # (RADD-1304); the *.read catalog atoms are revocable grants (RADD-816).
        permissions=(
            "item.read@own",
            "item.read@participant",
            *OWN_TICKET,
            *SHARED_TICKET,
            "worklog.delete@own",
            Permission.LABEL_READ,
            Permission.CYCLE_READ,
            Permission.CANNED_READ,
            Permission.TEAM_READ,
            Permission.ROLE_READ,
            Permission.CARD_PRESET_READ,
        ),
        position=-1,
    ),
    # --- RADD-1302: ONE ladder, Viewer ⊂ Member ⊂ Manager, at BOTH scopes: on a
    # project the item atoms apply, on a wiki space the page atoms, instance-wide both.
    BuiltinRole(
        key=BuiltinRoleKey.MANAGER,
        name="Manager",
        description=(
            "Runs a project or a wiki space. On a project: everything a Member does, "
            "plus its settings — workflow, fields, issue types, members, releases, "
            "SLAs and intake forms. On a space: edit, delete and restore its pages."
        ),
        # Every project-scoped atom + page.manage (⇒ page.write ⇒ page.read).
        # dashboard.create is the one global rider an instance-wide grant has always carried.
        permissions=PROJECT_PERMISSIONS + (Permission.PAGE_MANAGE, Permission.DASHBOARD_CREATE),
        position=0,
    ),
    BuiltinRole(
        key=BuiltinRoleKey.MEMBER,
        name="Member",
        description=(
            "Day-to-day work. On a project: create and edit issues, comment (internal "
            "notes too), log time and keep views. On a space: write pages."
        ),
        # Viewer's atoms + the day-to-day writes. form.manage LEFT for Manager
        # (RADD-1302): intake forms are project configuration.
        permissions=(
            Permission.ITEM_READ,
            Permission.PAGE_READ,
            Permission.ITEM_CREATE,
            Permission.ITEM_UPDATE,
            Permission.WORKLOG_WRITE,
            Permission.COMMENT_WRITE,
            Permission.COMMENT_READ_INTERNAL,
            Permission.VIEW_CREATE,
            Permission.VIEW_UPDATE,
            Permission.VIEW_DELETE,
            Permission.PAGE_WRITE,
        ),
        position=1,
    ),
    BuiltinRole(
        key=BuiltinRoleKey.VIEWER,
        name="Viewer",
        description=(
            "Read-only. On a project: its issues. On a space: its pages."
        ),
        permissions=(Permission.ITEM_READ, Permission.PAGE_READ),
        position=2,
    ),
    BuiltinRole(
        key=BuiltinRoleKey.REQUESTER,
        name="Requester",
        description=(
            "The floor for email-provisioned requester accounts (never the "
            "Baseline): their own tickets, commenting and attaching on them, "
            "and nothing else — not other items, not the wiki."
        ),
        # item.read@own is the whole visibility story: every child surface
        # inherits it through the item seam. Same floor shape as the Baseline.
        permissions=(
            "item.read@own",
            "item.read@participant",
            *OWN_TICKET,
            *SHARED_TICKET,
        ),
        position=3,
    ),
    BuiltinRole(
        key=BuiltinRoleKey.PUBLIC,
        name="Public",
        description=(
            "What the world holds on a public project: its public issues, their "
            "public comments and attachments, and the labels, cycles and teams "
            "needed to render them. Granted to Anyone by the Public project switch."
        ),
        # @public is a property of the ROW (spec 121), so internal/restricted
        # issues never reach the world. page.read makes a SPACE public when the
        # role is granted there (RADD-1147); on a project it is inert.
        permissions=(
            "item.read@public",
            Permission.PAGE_READ,
            Permission.LABEL_READ,
            Permission.CYCLE_READ,
            Permission.TEAM_READ,
        ),
        position=4,
    ),
    BuiltinRole(
        key=BuiltinRoleKey.CONTRIBUTOR,
        name="Contributor",
        description=(
            "What anyone with an account may do on a public project: file issues, "
            "comment, attach, and edit what they filed. Reading comes from Public. "
            "Granted to Signed-in users by the contributions switch."
        ),
        # Discussion is open on a public project; the rest of OWN_TICKET on top.
        permissions=(
            Permission.ITEM_CREATE,
            "item.update@own",
            Permission.COMMENT_WRITE,
            Permission.ATTACHMENT_CREATE,
            *(atom for atom in OWN_TICKET if atom.split("@")[0] not in ("comment.write", "attachment.create")),
        ),
        position=5,
    ),
)

class AuthEvent(StrEnum):
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    # Spec 89: once the row is gone, this payload IS the record they existed.
    USER_DELETED = "user.deleted"
    ROLE_CREATED = "role.created"
    ROLE_UPDATED = "role.updated"
    ROLE_DELETED = "role.deleted"
    # RADD-836: audited on entry AND exit, naming both parties.
    VIEW_AS_STARTED = "auth.view_as_started"
    VIEW_AS_ENDED = "auth.view_as_ended"
    MFA_RESET = "auth.mfa_reset"  # RADD-1279: an admin removed someone's TOTP enrolment
    # Spec 123: the spec-121 switches in the project's own history (the grant
    # rows underneath emit role.updated too).
    PROJECT_PUBLIC_ACCESS_CHANGED = "project.public_access_changed"


class LoginMethod(StrEnum):
    """RADD-1279: HOW a session is minted — required by `create_session`, the one
    seam the MFA policy is enforced at. LDAP/SSO: the IdP owns MFA."""

    PASSWORD = "password"
    PASSWORD_TOTP = "password_totp"
    LDAP = "ldap"
    SSO = "sso"


class AuthEntity(StrEnum):
    USER = "user"
    SESSION = "session"
    API_TOKEN = "api_token"
    ROLE = "role"
    GLOBAL_GRANT = "global_role_grant"  # spec 87 — instance-wide role assignment


class UserChange(StrEnum):
    """`action` values in user.updated event payloads."""

    PROFILE_UPDATED = "profile_updated"  # self-service name/avatar/timezone (spec 34)
    ADMIN_UPDATED = "admin_updated"  # PATCH /users/{id}: active/name by an instance admin (spec 84)
    DIRECTORY_DEACTIVATED = "directory_deactivated"  # spec 85 user sync: gone from the directory
