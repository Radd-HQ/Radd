from dataclasses import dataclass
from enum import StrEnum

# Wire-format constants (not tunables — changing them invalidates existing clients/tokens).
SESSION_COOKIE_NAME = "radd_session"
PAT_PREFIX = "radd_pat_"
PAT_PREFIX_DISPLAY_CHARS = 12  # how much of a token the UI may keep showing


class InstanceRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class UserSource(StrEnum):
    """Where an account came from (spec 84). Set at creation going forward;
    pre-existing rows were backfilled local (password hash present) / unknown."""

    LOCAL = "local"  # password login (register/seed/POST /users)
    LDAP = "ldap"  # provisioned by a directory bind or AD import
    OIDC = "oidc"  # provisioned by the OIDC callback
    JIRA = "jira"  # placeholder provisioned by the Jira importer (spec 90 follow-up)
    SERVICE = "service"  # spec 113 — a service account; authenticates by API key ONLY
    UNKNOWN = "unknown"  # pre-spec-84 SSO-only rows (upgraded on next login)


class DuplicateKind(StrEnum):
    """Why GET /users/duplicates grouped some accounts together (spec 84)."""

    EMAIL_LOCAL_PART = "email_local_part"  # same lowercased local part before the @
    NAME = "name"  # same case-insensitive display name


class Permission(StrEnum):
    """One member per action class an endpoint can demand (enforced via authz.require)."""

    GLOBAL_MANAGE = "global.manage"  # global settings + administration (was workspace.manage)
    PROJECT_CREATE = "project.create"
    PROJECT_MANAGE = "project.manage"  # states/fields/labels/webhooks/teams/members
    CYCLE_MANAGE = "cycle.manage"  # create/edit/delete cycles — global scope
    ITEM_READ = "item.read"
    ITEM_CREATE = "item.create"
    ITEM_UPDATE = "item.update"
    WORKLOG_WRITE = "worklog.write"  # project-scoped; log work + manage own worklogs (spec 22)
    TIMESHEET_VIEW = "timesheet.view"  # global-scoped; see others' timesheets (spec 22)
    COMMENT_WRITE = "comment.write"
    COMMENT_READ_INTERNAL = "comment.read_internal"
    VIEW_MANAGE = "view.manage"
    FORM_MANAGE = "form.manage"  # project-scoped; create/edit/delete intake forms (spec 17)
    TEAM_MANAGE = "team.manage"
    ROLE_MANAGE = "role.manage"  # global-scoped; admins hold it implicitly
    USER_MANAGE = "user.manage"
    AUTOMATION_MANAGE = "automation.manage"  # manage automation rules — global scope (spec 15)
    SLA_MANAGE = "sla.manage"  # manage SLA policies — global scope (specs 30/67)
    # Per-entity manage actions (spec 36) — previously folded into project.manage /
    # global.manage; the umbrellas still imply them (IMPLIED_PERMISSIONS).
    STATE_MANAGE = "state.manage"  # project workflow states
    RELEASE_MANAGE = "release.manage"  # project releases/versions
    FIELD_MANAGE = "field.manage"  # custom-field definitions + field access rules
    LABEL_MANAGE = "label.manage"  # labels (global)
    WEBHOOK_MANAGE = "webhook.manage"  # webhook endpoints (global)
    CANNED_MANAGE = "canned.manage"  # canned responses (global)
    CARD_PRESET_MANAGE = "cardpreset.manage"  # card-layout preset library (global, spec 109)
    # Wiki (spec 43) — SPACE-scoped since RADD-791 (they were global; a page had
    # no scope, which is why per-space access was inexpressible).
    PAGE_READ = "page.read"  # read page spaces/pages + doc search
    PAGE_WRITE = "page.write"  # create/edit/move/archive pages, link items
    PAGE_MANAGE = "page.manage"  # manage spaces, hard-delete + restore pages
    # --- Full CRUD atoms (spec 50) -----------------------------------------
    # Every resource exposes create/update/delete as independently grantable
    # atoms; the coarse verbs above are retained as umbrellas that expand to
    # them (IMPLIED_PERMISSIONS, applied transitively). READS stay open to
    # members (the open-visibility default) — value-level read
    # restriction lives in the field-grant (spec 07/50) and comment-visibility
    # (spec 50) systems, not here. Content create/update keep their existing
    # atoms/verbs (a comment has no create-vs-edit capability split); only the
    # missing DELETEs are added. Config resources gain the full C/U/D triple.
    ITEM_DELETE = "item.delete"  # hard-delete work items (was project.manage)
    COMMENT_DELETE = "comment.delete"  # delete others' comments (author deletes own)
    WORKLOG_DELETE = "worklog.delete"  # delete others' worklogs (author deletes own)
    PAGE_DELETE = "page.delete"  # hard-delete pages (rides page.manage)
    # Attaching a file is its OWN authority (RADD-790). It used to be
    # `item.update`, which conflated "may edit this issue's fields" with "may add
    # a file to it": a role built to let someone discuss an issue without editing
    # it (item.read + comment.write) posted a comment fine and 403'd the moment
    # the editor uploaded a pasted screenshot — so it read as "commenting is
    # broken". A reviewer who must not retitle an issue should still be able to
    # attach the crash log they are describing.
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
    SERVICE_ACCOUNT_DELETE = "service_account.delete"
    # Spec 111 — version-control connections (Forgejo/Gitea hosts + repos).
    VCSCONN_CREATE = "vcsconn.create"
    VCSCONN_UPDATE = "vcsconn.update"
    VCSCONN_DELETE = "vcsconn.delete"
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
    # Spec 87 dropped `user.delete` on the reasoning that accounts are only ever
    # deactivated or merged. Spec 89 reinstates it: hard deletion IS possible,
    # provided the account's authored work is reassigned to a named successor
    # first (`DELETE /users/{id}?reassign_to=…`).
    USER_DELETE = "user.delete"
    # Dashboards (spec 75) — global-scoped; dashboard.create is ALSO the
    # broadcast gate on `dashboards.global_access` (the view.create idiom).
    # Spec 87 dropped dashboard.update/delete: dashboards shipped with the
    # spec-57 ownership model from birth, so editing and deleting are decided by
    # owner/editor grants and no atom was ever consulted.
    DASHBOARD_CREATE = "dashboard.create"


class CrudAction(StrEnum):
    """The four verbs of the resource × action matrix (spec 50)."""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"


class PermissionScope(StrEnum):
    """Where a permission is checked — drives the GET /permissions catalog.

    2026-07-22 named the middle scope GLOBAL; spec 86 stage 3 finished the
    job — the workspace entity is gone and the umbrella atom is
    `global.manage` (stored role JSONB migrated).

    RADD-814 retired the `instance` tier: it carried zero atoms and had no
    resolution branch — dead vocabulary that made the ladder look four rungs
    tall when it has three. The containment ladder is
    `global ⊃ {project | space}` (see `checkable_at`)."""

    PROJECT = "project"
    GLOBAL = "global"
    #: RADD-791 — checked against a WIKI SPACE. The page atoms moved here from
    #: GLOBAL: a space is a scope the way a project is, so "read-only space" and
    #: "who may comment here" are ordinary role grants rather than new vocabulary.
    SPACE = "space"


class GrantScopeKind(StrEnum):
    """What a role grant can be scoped TO (RADD-791).

    A grant is either instance-wide (no scope) or bound to one scoped thing. Two
    kinds exist: a project, and a wiki space.

    Spelled as an enum rather than left implicit in column names because a scope
    names a behaviour, and dev rule 2 puts those in a StrEnum. The columns stay
    typed and foreign-keyed (`project_id`, `space_id`) rather than collapsing to
    a polymorphic `(scope_type, scope_id)` pair: a polymorphic column cannot
    carry an FK, and trading referential integrity on the permission table for a
    third scope nobody has asked for is a speculative framework (dev rule 5).
    Adding one later is a column and ten lines here.
    """

    PROJECT = "project"
    SPACE = "space"


PERMISSION_SCOPES: dict[Permission, PermissionScope] = {
    Permission.GLOBAL_MANAGE: PermissionScope.GLOBAL,
    Permission.PROJECT_CREATE: PermissionScope.GLOBAL,
    Permission.PROJECT_MANAGE: PermissionScope.PROJECT,
    Permission.CYCLE_MANAGE: PermissionScope.GLOBAL,
    Permission.ITEM_READ: PermissionScope.PROJECT,
    Permission.ITEM_CREATE: PermissionScope.PROJECT,
    Permission.ITEM_UPDATE: PermissionScope.PROJECT,
    Permission.WORKLOG_WRITE: PermissionScope.PROJECT,
    Permission.TIMESHEET_VIEW: PermissionScope.GLOBAL,
    Permission.COMMENT_WRITE: PermissionScope.PROJECT,
    Permission.COMMENT_READ_INTERNAL: PermissionScope.PROJECT,
    Permission.VIEW_MANAGE: PermissionScope.PROJECT,
    Permission.FORM_MANAGE: PermissionScope.PROJECT,
    Permission.TEAM_MANAGE: PermissionScope.GLOBAL,
    Permission.ROLE_MANAGE: PermissionScope.GLOBAL,
    Permission.USER_MANAGE: PermissionScope.GLOBAL,
    Permission.AUTOMATION_MANAGE: PermissionScope.GLOBAL,
    Permission.SLA_MANAGE: PermissionScope.GLOBAL,
    Permission.STATE_MANAGE: PermissionScope.PROJECT,
    Permission.RELEASE_MANAGE: PermissionScope.PROJECT,
    Permission.FIELD_MANAGE: PermissionScope.PROJECT,
    Permission.LABEL_MANAGE: PermissionScope.GLOBAL,
    Permission.WEBHOOK_MANAGE: PermissionScope.GLOBAL,
    Permission.CANNED_MANAGE: PermissionScope.GLOBAL,
    Permission.CARD_PRESET_MANAGE: PermissionScope.GLOBAL,
    # RADD-791: the page atoms are SPACE-scoped now. They were global because a
    # page had no scope to be checked against, which made per-space access
    # inexpressible and dropped page commenting on the floor — the comments
    # binding resolved `comment.write` with project=None, so a project-scoped
    # grant never reached it. A grant with no scope still applies everywhere.
    Permission.PAGE_READ: PermissionScope.SPACE,
    Permission.PAGE_WRITE: PermissionScope.SPACE,
    Permission.PAGE_MANAGE: PermissionScope.SPACE,
}

PERMISSION_DESCRIPTIONS: dict[Permission, str] = {
    Permission.GLOBAL_MANAGE: "Administer global settings and shared configuration.",
    Permission.PROJECT_CREATE: "Create projects (global).",
    Permission.PROJECT_MANAGE: "Manage a project: states, fields, labels, teams, members.",
    Permission.CYCLE_MANAGE: "Create and manage cycles (global).",
    Permission.ITEM_READ: "See the project's work items.",
    Permission.ITEM_CREATE: "Create work items in the project.",
    Permission.ITEM_UPDATE: "Edit the project's work items.",
    Permission.WORKLOG_WRITE: "Log work on items and manage your own worklogs.",
    Permission.TIMESHEET_VIEW: "See other people's timesheets (global).",
    Permission.COMMENT_WRITE: "Comment on the project's work items.",
    Permission.COMMENT_READ_INTERNAL: "See internal (team-only) comments.",
    Permission.VIEW_MANAGE: "Create and edit the project's saved views.",
    Permission.FORM_MANAGE: "Create and manage the project's intake forms.",
    Permission.TEAM_MANAGE: "Create teams and manage their memberships.",
    Permission.ROLE_MANAGE: "Create, edit, and delete roles (global).",
    Permission.USER_MANAGE: "Create users and see the user directory.",
    Permission.AUTOMATION_MANAGE: "Create and manage automation rules (global).",
    Permission.SLA_MANAGE: "Create and manage SLA policies (global).",
    Permission.STATE_MANAGE: "Manage the project's workflow states.",
    Permission.RELEASE_MANAGE: "Manage the project's releases/versions.",
    Permission.FIELD_MANAGE: "Manage custom-field definitions and field access rules.",
    Permission.LABEL_MANAGE: "Create and manage labels (global).",
    Permission.WEBHOOK_MANAGE: "Manage webhook endpoints (global).",
    Permission.CANNED_MANAGE: "Manage canned responses (global).",
    Permission.CARD_PRESET_MANAGE: "Manage the shared card-layout preset library (global).",
    Permission.PAGE_READ: "Read a wiki space and its pages.",
    Permission.PAGE_WRITE: "Create and edit pages in a space; link them to issues.",
    Permission.PAGE_MANAGE: "Manage a space; hard-delete and restore its pages.",
}

# Umbrella permissions imply their per-entity actions (spec 36) — so pre-existing
# roles holding project.manage keep full project control with zero backfill logic
# at check time, while custom roles can now grant the granular actions alone.
# Spec 50 extends this: each *.manage also implies its resource's CRUD atoms
# (registered below), and expansion is applied transitively so project.manage ->
# state.manage -> state.create/update/delete all resolve in one pass.
IMPLIED_PERMISSIONS: dict[Permission, frozenset[Permission]] = {
    Permission.PROJECT_MANAGE: frozenset(
        {Permission.STATE_MANAGE, Permission.RELEASE_MANAGE, Permission.FIELD_MANAGE}
    ),
    # RADD-790: anyone who may edit an issue may attach to it. This is what makes
    # splitting attachments off `item.update` a WIDENING and never a downgrade —
    # every existing role keeps exactly what it had, with no data migration, and
    # a role created tomorrow inherits the same rule. A backfill would have fixed
    # only the rows that existed on the day it ran.
    Permission.ITEM_UPDATE: frozenset(
        {Permission.ATTACHMENT_CREATE, Permission.ATTACHMENT_DELETE}
    ),
    Permission.GLOBAL_MANAGE: frozenset(
        {
            Permission.LABEL_MANAGE,
            Permission.WEBHOOK_MANAGE,
            Permission.CANNED_MANAGE,
            Permission.CARD_PRESET_MANAGE,
        }
    ),
}


# --- resource × CRUD registry (spec 50) --------------------------------------


@dataclass(frozen=True)
class ResourceSpec:
    """A resource exposing granular create/update/delete atoms + its umbrella."""

    key: str
    scope: PermissionScope
    label: str
    manage: Permission  # the coarse verb whose holders get all of this resource's atoms
    actions: tuple[CrudAction, ...] = (CrudAction.CREATE, CrudAction.UPDATE, CrudAction.DELETE)


# Every config resource with a full grantable create/update/delete triple. Reads
# stay open to members (value-level read restriction is field grants /
# comment visibility, not these) so there is no `read` atom here by design.
CRUD_RESOURCES: tuple[ResourceSpec, ...] = (
    ResourceSpec("state", PermissionScope.PROJECT, "workflow states", Permission.STATE_MANAGE),
    ResourceSpec("field", PermissionScope.PROJECT, "custom fields", Permission.FIELD_MANAGE),
    ResourceSpec("release", PermissionScope.PROJECT, "releases", Permission.RELEASE_MANAGE),
    ResourceSpec("form", PermissionScope.PROJECT, "intake forms", Permission.FORM_MANAGE),
    ResourceSpec("view", PermissionScope.PROJECT, "saved views", Permission.VIEW_MANAGE),
    ResourceSpec("member", PermissionScope.PROJECT, "project access", Permission.PROJECT_MANAGE),
    ResourceSpec("issue_type", PermissionScope.PROJECT, "issue types", Permission.PROJECT_MANAGE),
    ResourceSpec("label", PermissionScope.GLOBAL, "labels", Permission.LABEL_MANAGE),
    ResourceSpec("webhook", PermissionScope.GLOBAL, "webhooks", Permission.WEBHOOK_MANAGE),
    ResourceSpec("canned", PermissionScope.GLOBAL, "canned responses", Permission.CANNED_MANAGE),
    # Spec 109: the shared board-card layout preset library.
    ResourceSpec(
        "cardpreset", PermissionScope.GLOBAL, "card layout presets", Permission.CARD_PRESET_MANAGE
    ),
    ResourceSpec(
        "automation", PermissionScope.GLOBAL, "automation rules", Permission.AUTOMATION_MANAGE
    ),
    ResourceSpec("cycle", PermissionScope.GLOBAL, "cycles", Permission.CYCLE_MANAGE),
    ResourceSpec("sla", PermissionScope.GLOBAL, "SLA policies", Permission.SLA_MANAGE),
    ResourceSpec("team", PermissionScope.GLOBAL, "teams", Permission.TEAM_MANAGE),
    ResourceSpec("role", PermissionScope.GLOBAL, "roles", Permission.ROLE_MANAGE),
    # Spec 89 restored the full triple: deleting a user is real, and gated by
    # reassigning their work rather than by the atom not existing.
    ResourceSpec("user", PermissionScope.GLOBAL, "users", Permission.USER_MANAGE),
    # Spec 75: no dashboard.manage coarse verb exists — the umbrella is
    # global.manage directly (the member/issue_type precedent). Spec 87: create
    # only — dashboard.create is the broadcast gate on `global_access`, while
    # editing and deleting are owner/editor decisions (spec-57 ownership), not atoms.
    ResourceSpec(
        "dashboard",
        PermissionScope.GLOBAL,
        "dashboards",
        Permission.GLOBAL_MANAGE,
        actions=(CrudAction.CREATE,),
    ),
    # Spec 111: Forgejo/Gitea hosts and their repositories. No coarse verb of its
    # own — the umbrella is global.manage, the dashboard precedent.
    ResourceSpec(
        "vcsconn", PermissionScope.GLOBAL, "version-control connections", Permission.GLOBAL_MANAGE
    ),
    # Spec 113: service accounts sit beside users but are managed separately —
    # granting someone the ability to mint agent keys is not the same as granting
    # them the ability to edit people.
    ResourceSpec(
        "service_account", PermissionScope.GLOBAL, "service accounts", Permission.GLOBAL_MANAGE
    ),
)

_ACTION_VERB: dict[CrudAction, str] = {
    CrudAction.CREATE: "Create",
    CrudAction.UPDATE: "Edit",
    CrudAction.DELETE: "Delete",
}

# (resource_key, action) -> the Permission atom that governs it (drives the roles matrix).
CRUD_MATRIX: dict[tuple[str, CrudAction], Permission] = {}

for _res in CRUD_RESOURCES:
    _implied: set[Permission] = set(IMPLIED_PERMISSIONS.get(_res.manage, frozenset()))
    for _action in _res.actions:
        _perm = Permission(f"{_res.key}.{_action.value}")
        PERMISSION_SCOPES[_perm] = _res.scope
        PERMISSION_DESCRIPTIONS[_perm] = f"{_ACTION_VERB[_action]} {_res.label}."
        CRUD_MATRIX[(_res.key, _action)] = _perm
        _implied.add(_perm)
    IMPLIED_PERMISSIONS[_res.manage] = frozenset(_implied)

# Content deletes — create/read/update keep their pre-existing atoms/verbs; only
# the previously-missing delete verb is minted, riding the resource's admin umbrella.
for _perm, _scope, _desc, _umbrella in (
    (Permission.ITEM_DELETE, PermissionScope.PROJECT, "Hard-delete work items.",
     Permission.PROJECT_MANAGE),
    (Permission.COMMENT_DELETE, PermissionScope.PROJECT, "Delete other people's comments.",
     Permission.PROJECT_MANAGE),
    (Permission.WORKLOG_DELETE, PermissionScope.PROJECT, "Delete other people's worklogs.",
     Permission.PROJECT_MANAGE),
    (Permission.PAGE_DELETE, PermissionScope.SPACE, "Hard-delete pages.",
     Permission.PAGE_MANAGE),
    # RADD-790. Project-scoped like the item they hang off; both ride
    # project.manage, and `item.update` implies them too (see below) so no role
    # that can edit an issue loses the ability to attach to it.
    (Permission.ATTACHMENT_CREATE, PermissionScope.PROJECT,
     "Attach files to items and comments.", Permission.PROJECT_MANAGE),
    (Permission.ATTACHMENT_DELETE, PermissionScope.PROJECT,
     "Remove your own attachments.", Permission.PROJECT_MANAGE),
):
    PERMISSION_SCOPES[_perm] = _scope
    PERMISSION_DESCRIPTIONS[_perm] = _desc
    IMPLIED_PERMISSIONS[_umbrella] = IMPLIED_PERMISSIONS.get(_umbrella, frozenset()) | {_perm}


def implied_map() -> dict[str, frozenset[str]]:
    """The umbrella→implied closure — builtin `IMPLIED_PERMISSIONS` MERGED with
    plugin-contributed CRUD resources (spec 93/A2): a plugin's `manage` umbrella
    implies its `key.action` atoms, read live from the kernel registry. In the
    default config (no plugin CRUD resources) this equals the builtin map exactly."""
    merged: dict[str, frozenset[str]] = {
        str(k): frozenset(str(x) for x in v) for k, v in IMPLIED_PERMISSIONS.items()
    }
    from radd.kernel import registries

    for spec in registries.crud_resources.values():
        atoms = frozenset(f"{spec.key}.{a}" for a in spec.actions)
        merged[spec.manage] = merged.get(spec.manage, frozenset()) | atoms
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


# Every project-scoped permission, in enum order (the builtin admin role's grant set).
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


# --- RADD-823: relations — an atom qualified by who you are to the record -----
#
# `resource.action@relation` is the normative syntax (D-review note: never the
# dotted form). An UNQUALIFIED atom means `@any` — `item.update` and
# `item.update@any` are the same fact, which is what makes migration free:
# every existing role keeps exactly what it had, with zero backfill.
#
# The relation lattice is a CHAIN, widest first: any ⊃ team ⊃ own. Holding a
# wider relation satisfies a narrower need; the MEET of two relations is the
# narrower one. What a relation MEANS for a resource's rows is the owning
# module's `RelationSpec` in the kernel registry — this vocabulary is pure
# string algebra and never touches a table.

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


def permission_relation(key: "Permission | str") -> str:
    return split_permission(key)[1]


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


# --- plugin-contributable RBAC (spec 93 / A2) --------------------------------
# Permission atoms and CRUD resources are no longer a closed enum + tuple: a
# plugin declares `permissions=(PermissionSpec…)` / `crud_resources=(CrudResource
# Spec…)` in its manifest, the loader puts them in the kernel registry, and these
# merged-view accessors fold them in LIVE. Builtins come from the enum/tuple
# above; the two are unioned so the roles matrix / catalog / admin set all include
# plugin atoms with no edits to auth. In the default config the registry is empty,
# so every accessor returns exactly the builtin set.


def _registered_crud_atoms() -> dict[str, tuple["PermissionScope", str]]:
    """{atom: (scope, description)} for every plugin CRUD resource's atoms + umbrella."""
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
    """{key: (scope, description)} for every plugin-contributed standalone atom."""
    from radd.kernel import registries

    return {
        spec.key: (PermissionScope(spec.scope), spec.description)
        for spec in registries.permissions.values()
    }


def _all_registered() -> dict[str, tuple["PermissionScope", str]]:
    return {**_registered_crud_atoms(), **_registered_atoms()}


def all_permission_keys() -> frozenset[str]:
    """Every atom the system knows: builtin enum ∪ plugin-registered."""
    return frozenset({p.value for p in Permission} | set(_all_registered()))


def permission_scope_of(key: "Permission | str") -> "PermissionScope":
    # PERMISSION_SCOPES is keyed by Permission (a StrEnum), so a plain-string
    # lookup resolves a builtin atom; else fall to the plugin registry. A
    # relation qualifier never changes WHERE an atom is checked (RADD-823):
    # scope is the grant's axis, relation is the atom's — resolve the base.
    scope = PERMISSION_SCOPES.get(base_permission(key))  # type: ignore[arg-type]
    if scope is not None:
        return scope
    reg = _all_registered().get(base_permission(key))
    return reg[0] if reg else PermissionScope.GLOBAL


# --- RADD-814: scope is a property of the GRANT, not the atom -----------------
#
# The containment ladder:   global  ⊃  {project | space}
#
# A grant at an outer scope satisfies a check at any scope it contains — which
# has always been the resolver's de-facto behaviour (`_granted_role_ids` unions
# global grants into every project), declared nowhere. `CHECKABLE_AT` names the
# scopes an atom can be CHECKED at. Day one it is behaviour-identical: every
# atom carries its old single scope, and `PERMISSION_SCOPES` survives as the
# catalog's PRIMARY grouping. Widening an atom to a second scope is one
# reviewable line in `_CHECKABLE_WIDENINGS`, never a rewrite.

_CHECKABLE_WIDENINGS: dict[str, frozenset[PermissionScope]] = {}


def checkable_at(key: "Permission | str") -> frozenset[PermissionScope]:
    """The scope kinds this atom can be checked at (RADD-814). Single-member for
    every atom today; the matrix (RADD-815) and the RADD-810 contract read it."""
    return frozenset({permission_scope_of(key)}) | _CHECKABLE_WIDENINGS.get(
        base_permission(key), frozenset()
    )


def permission_description_of(key: "Permission | str") -> str:
    desc = PERMISSION_DESCRIPTIONS.get(base_permission(key))  # type: ignore[arg-type]
    if desc is not None:
        return desc
    reg = _all_registered().get(base_permission(key))
    return reg[1] if reg else ""


class BuiltinRoleKey(StrEnum):
    """Keys of the seeded builtin roles (rows are immutable: is_builtin —
    except BASELINE, whose whole purpose is being edited; see below)."""

    #: What every active user holds, everywhere, without being granted anything
    #: (RADD-773). Undeletable like the others, but its permission set is the
    #: one an admin may change.
    BASELINE = "baseline"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


@dataclass(frozen=True)
class BuiltinRole:
    """Seed definition of a builtin role — the DB rows mirror these exactly (immutable)."""

    key: BuiltinRoleKey
    name: str
    description: str
    permissions: tuple[Permission, ...]
    position: int


BUILTIN_ROLES: tuple[BuiltinRole, ...] = (
    BuiltinRole(
        key=BuiltinRoleKey.BASELINE,
        name="Baseline",
        description=(
            "What everyone with an account gets, on every project, without being "
            "granted anything. Edit this to widen or narrow the floor."
        ),
        # Read-only on purpose (RADD-773). This used to be MEMBER_FLOOR plus a
        # wider global set carrying page.write, cycle.manage and timesheet.view
        # — so every member could edit any wiki page and delete any cycle, and
        # no screen anywhere said so. Those three are no longer free; grant them
        # through a role, or add them back here deliberately.
        #
        # item.read is project-scoped and page.read is global; the baseline is
        # applied at BOTH scopes, so each lands where it means something and the
        # other is inert. That is what preserves "any signed-in user can read the
        # wiki and see the projects" without a second constant to keep in step.
        permissions=(Permission.ITEM_READ, Permission.PAGE_READ),
        position=-1,
    ),
    BuiltinRole(
        key=BuiltinRoleKey.ADMIN,
        name="Admin",
        description="Full control of the project, including settings, views, and internal comments.",
        # Every project-scoped atom, plus dashboard.create as a global-scoped
        # rider (spec 75 — the page.write-on-member precedent; display parity
        # with the migration backfill, mirrored into stored rows by 75's
        # migration). Spec 87 dropped the update/delete riders along with the
        # atoms. Since spec 87 a global rider is no longer inert: an
        # instance-wide grant of this role delivers it.
        permissions=PROJECT_PERMISSIONS + (Permission.DASHBOARD_CREATE,),
        position=0,
    ),
    BuiltinRole(
        key=BuiltinRoleKey.MEMBER,
        name="Member",
        description="Day-to-day work: read, create, and update items; comment; manage views.",
        permissions=(
            Permission.ITEM_READ,
            Permission.ITEM_CREATE,
            Permission.ITEM_UPDATE,
            Permission.WORKLOG_WRITE,
            Permission.COMMENT_WRITE,
            Permission.COMMENT_READ_INTERNAL,
            Permission.VIEW_MANAGE,
            Permission.FORM_MANAGE,
            Permission.PAGE_WRITE,  # members write docs (spec 43; global-scoped rider)
        ),
        position=1,
    ),
    BuiltinRole(
        key=BuiltinRoleKey.VIEWER,
        name="Viewer",
        description="Read-only access to the project's items.",
        # page.read rides on the viewer set so it flows into the member floor
        # (spec 43) — any active user can read the wiki.
        permissions=(Permission.ITEM_READ, Permission.PAGE_READ),
        position=2,
    ),
)

_BUILTIN_BY_KEY: dict[BuiltinRoleKey, BuiltinRole] = {role.key: role for role in BUILTIN_ROLES}


def builtin_role(key: BuiltinRoleKey) -> BuiltinRole:
    return _BUILTIN_BY_KEY[key]


class AuthEvent(StrEnum):
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    # Spec 89 — hard delete. The payload keeps the email/name and what was
    # reassigned: once the row is gone, this event IS the record that they existed.
    USER_DELETED = "user.deleted"
    ROLE_CREATED = "role.created"
    ROLE_UPDATED = "role.updated"
    ROLE_DELETED = "role.deleted"
    # RADD-836 U1 — impersonation is audited on entry AND exit; the payload
    # names both parties, so the trail survives either account's deletion.
    VIEW_AS_STARTED = "auth.view_as_started"
    VIEW_AS_ENDED = "auth.view_as_ended"


class AuthEntity(StrEnum):
    USER = "user"
    SESSION = "session"
    API_TOKEN = "api_token"
    ROLE = "role"
    PROJECT_MEMBER = "project_member"
    GLOBAL_GRANT = "global_role_grant"  # spec 87 — instance-wide role assignment


class UserChange(StrEnum):
    """`action` values in user.updated event payloads."""

    PROJECT_MEMBER_ADDED = "project_member_added"
    PROJECT_MEMBER_ROLE_CHANGED = "project_member_role_changed"
    PROJECT_MEMBER_REMOVED = "project_member_removed"
    PROFILE_UPDATED = "profile_updated"  # self-service name/avatar/timezone (spec 34)
    ADMIN_UPDATED = "admin_updated"  # PATCH /users/{id}: active/name by an instance admin (spec 84)
    DIRECTORY_DEACTIVATED = "directory_deactivated"  # spec 85 user sync: gone from the directory
