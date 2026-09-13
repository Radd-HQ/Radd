from collections.abc import Mapping
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


class DuplicateKind(StrEnum):
    """Why GET /users/duplicates grouped some accounts together (spec 84)."""

    EMAIL_LOCAL_PART = "email_local_part"  # same lowercased local part before the @
    NAME = "name"  # same case-insensitive display name


class Permission(StrEnum):
    """One member per action class an endpoint can demand (enforced via authz.require).

    RADD-890: this enum is no longer the CATALOG — it is the typed alias surface
    for call sites. Every atom below is DECLARED by the module that enforces it
    (`permissions=(PermissionSpec…)` / `crud_resources=(CrudResourceSpec…)` on
    its `RaddPlugin`), and the kernel permissions registry is what
    `all_permission_keys`, `permission_scope_of`, `permission_description_of`,
    `implied_map`, role validation and `GET /permissions` compose from. A new
    module atom needs no edit here at all — the milestones plugin has always
    worked that way, and now `item.read` works the same way.

    Two things keep the alias honest. `tests/test_permission_ownership.py`
    asserts registry ⊆ enum AND enum ⊆ registry, with matching scopes, so an
    atom added here alone (or moved there alone) fails the suite. And auth
    itself declares only the governance atoms it enforces
    (`_AUTH_OWNED_RESOURCES` / `AUTH_PERMISSIONS` in `permissions.py`).

    Why the alias survives at all: `PROJECT_PERMISSIONS` — and through it the
    seeded Admin builtin role — is computed when THIS module is imported, which
    is long before any feature plugin's manifest exists (auth is the third
    module loaded). A `Permission` built from the registry would make the admin
    role a function of import order; the members here, plus `_PROJECT_SCOPED`
    below, are the minimum auth must know at import time, and the ratchet is
    what stops that minimum from drifting."""

    GLOBAL_MANAGE = "global.manage"  # global settings + administration (was workspace.manage)
    PROJECT_CREATE = "project.create"
    PROJECT_MANAGE = "project.manage"  # states/fields/labels/webhooks/teams/members
    ITEM_READ = "item.read"
    ITEM_CREATE = "item.create"
    ITEM_UPDATE = "item.update"
    WORKLOG_WRITE = "worklog.write"  # project-scoped; log work + manage own worklogs (spec 22)
    TIMESHEET_VIEW = "timesheet.view"  # global-scoped; see others' timesheets (spec 22)
    COMMENT_WRITE = "comment.write"
    COMMENT_READ_INTERNAL = "comment.read_internal"
    FORM_MANAGE = "form.manage"  # project-scoped; create/edit/delete intake forms (spec 17)
    USER_MANAGE = "user.manage"
    AUTOMATION_MANAGE = "automation.manage"  # manage automation rules — global scope (spec 15)
    # Build automations whose actions run as SOMEONE ELSE (spec 116). Without it
    # an author's automations always act as the author; the field is not offered
    # in the editor at all, and the API refuses it, so the two agree.
    AUTOMATION_ACT_AS = "automation.act_as"
    # Per-entity manage actions (spec 36) — previously folded into project.manage /
    # global.manage; the umbrellas still imply them (IMPLIED_PERMISSIONS).
    STATE_MANAGE = "state.manage"  # project workflow states
    # RADD-816: nine manage umbrellas with ZERO direct enforcement sites
    # (view/cycle/label/release/canned/cardpreset/sla/team/role) are DELETED
    # — granting one was exactly ticking its triple, a third checkbox whose
    # only meaning was the other three. The migration rewrites stored roles
    # to the triples; no alias survives (the no-backcompat rule).
    # `service_account.delete` had no route and is gone the same way.
    FIELD_MANAGE = "field.manage"  # custom-field definitions + field access rules
    WEBHOOK_MANAGE = "webhook.manage"  # webhook endpoints (global)
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
    # RADD-816 (F6): READ becomes deliverable for the config catalogs that
    # used to ride the member floor — seeded into the Baseline so day-one
    # behaviour is identical, and REVOCABLE for the first time.
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


# --- scope: the ONE fact auth must know at import time (RADD-890) -------------
#
# Everything else about an atom — its prose, its label, its umbrella, its CRUD
# family — is declared by the module that enforces it and read live from the
# kernel registry. Scope cannot be, because `PROJECT_PERMISSIONS` (and through
# it the seeded Admin builtin role) is computed while THIS module is imported,
# which happens before any feature plugin's manifest exists. So auth keeps one
# token per atom here, and `tests/test_permission_ownership.py` asserts it
# equals the owning module's declared scope — the copy cannot drift.

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
})

#: Atoms checked against a WIKI SPACE (RADD-791). They were global because a
#: page had no scope to be checked against, which made per-space access
#: inexpressible and dropped page commenting on the floor — the comments
#: binding resolved `comment.write` with project=None, so a project-scoped
#: grant never reached it. A grant with no scope still applies everywhere.
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


class _DescriptionCatalog(Mapping[str, str]):
    """`{atom: prose}` over the LIVE registry (RADD-890).

    A dict, until this change: auth carried one sentence per atom for every
    module in the system. The prose belongs with the endpoint that refuses —
    `pages` should be the thing that says what `page.write` means — so it moved
    to the owning module's `PermissionSpec`/`CrudResourceSpec`, and this reads
    it back. Presented as a Mapping rather than a function because the roles
    matrix and the catalog test both treat it as one, and because a missing
    entry should raise where it is asked for, not resolve to a lie.
    """

    def __getitem__(self, key: "Permission | str") -> str:
        entry = _all_registered().get(base_permission(key))
        if entry is None:
            raise KeyError(key)
        return entry[1]

    def __iter__(self):
        return iter(_all_registered())

    def __len__(self) -> int:
        return len(_all_registered())


PERMISSION_DESCRIPTIONS: Mapping[str, str] = _DescriptionCatalog()

# Umbrella permissions imply their per-entity actions (spec 36) — so pre-existing
# roles holding project.manage keep full project control with zero backfill logic
# at check time, while custom roles can now grant the granular actions alone.
# Spec 50 extends this: each *.manage also implies its resource's CRUD atoms, and
# expansion is applied transitively so project.manage -> state.manage ->
# state.create/update/delete all resolve in one pass.
#
# RADD-890 emptied this map. Every entry it held was a statement about another
# module's atoms — "project.manage covers workflow states", "editing an issue
# lets you attach to it" — and each is now declared where it is enforced, via
# `PermissionSpec.implied_by` / `.implies` and the `manage` umbrella on a
# `CrudResourceSpec`. `implied_map()` reads them back. It stays as the seam for
# an implication auth itself owns; there are none today.
IMPLIED_PERMISSIONS: dict[Permission, frozenset[Permission]] = {}


# --- resource × CRUD vocabulary (spec 50) ------------------------------------
#
# RADD-890 moved the RESOURCES out. `CRUD_RESOURCES` used to list every config
# resource in the system — states, fields, releases, forms, views, labels,
# webhooks, canned responses, card presets, automations, cycles, SLA policies,
# teams, roles, users, dashboards, VCS connections, service accounts — from
# inside auth, and the spec-93 `CrudResourceSpec` registry that exists for
# exactly this had one client (`milestones`). Each resource is now declared on
# the manifest of the plugin that serves its endpoints; auth declares its own
# four (user/role/member/service_account) the same way, through the same
# registry, with no special case.
#
# What stays here is the VOCABULARY the registry is expressed in: the four
# verbs, and how a verb reads in a sentence.

_ACTION_VERB: dict[CrudAction, str] = {
    CrudAction.CREATE: "Create",
    CrudAction.READ: "See",
    CrudAction.UPDATE: "Edit",
    CrudAction.DELETE: "Delete",
}


def implied_map() -> dict[str, frozenset[str]]:
    """The umbrella→implied closure, composed from the kernel registry.

    Three contributions, all read live so a hot-disabled plugin's umbrella stops
    expanding in the same breath its routes unmount:

      - a `CrudResourceSpec`'s `manage` umbrella implies its `key.action` atoms
        (spec 93/A2 — this half already worked, for plugins only);
      - a `PermissionSpec.implied_by` names the umbrellas that expand TO it
        (declared in spec 93, read by nothing until RADD-890 — which is why a
        plugin atom could not ride an umbrella at all);
      - a `PermissionSpec.implies` names what holding it confers, for the case
        `implied_by` cannot express: a RELATION-QUALIFIED form that is not
        itself a catalog atom (`item.update` -> `attachment.delete@own`).

    `IMPLIED_PERMISSIONS` is merged first and is empty today — every implication
    the system has is a statement about some module's own atoms.
    """
    merged: dict[str, frozenset[str]] = {
        str(k): frozenset(str(x) for x in v) for k, v in IMPLIED_PERMISSIONS.items()
    }

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


# --- the catalog: composed from the kernel registry (spec 93 / A2, RADD-890) --
# A module declares `permissions=(PermissionSpec…)` / `crud_resources=(CrudResource
# Spec…)` on its manifest, the loader puts them in the kernel registry, and these
# accessors are what every consumer reads — the roles matrix, GET /permissions,
# the admin's effective set, role validation, the scope validator.
#
# Spec 93 built this for PLUGINS while core atoms stayed hardcoded in auth, so
# the platform had two ways to define an atom and only one of them was used by
# anything shipped. RADD-890 deleted the second: `items` declares `item.read`
# through exactly the seam `milestones` uses, and these functions no longer
# distinguish "builtin" from "contributed" because there is no difference left.
# The union with the enum below is what keeps a *disabled* module's atoms
# addressable in stored roles (RADD-818 sweeps them on uninstall, not disable).


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
    """The owning module's sentence for this atom; "" once its plugin is
    disabled — the atom is still addressable in stored roles, but nothing is
    left to describe it."""
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
    #: RADD-828 (Q1): the INTERNET-facing floor — what an email-provisioned
    #: requester holds INSTEAD of the Baseline, so enabling mail ingest can
    #: never hand strangers the operator's staff policy row.
    REQUESTER = "requester"
    #: Spec 121 — what the WORLD holds on a public project: granted to the
    #: Anyone principal, project-scoped, by the "Public project" switch.
    PUBLIC = "public"
    #: Spec 121 — what anyone with an account may do on a public project:
    #: granted to the Signed-in users principal by the "contributions" switch.
    CONTRIBUTOR = "contributor"


@dataclass(frozen=True)
class BuiltinRole:
    """Seed definition of a builtin role — the DB rows mirror these exactly (immutable)."""

    key: BuiltinRoleKey
    name: str
    description: str
    permissions: "tuple[Permission | str, ...]"
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
        # RADD-825 (Q2): the floor is item.read@OWN — a signed-in user sees the
        # issues they reported until a role grants more. page.read left with it
        # (N5: a floor page.read defeated every restricted space). Existing
        # deployments keep today's effective access through the Staff role the
        # d825flip migration seeds and grants to the accounts that predate it.
        permissions=(
            "item.read@own",
            # RADD-844: the second-reporter floor. A share means something —
            # a participant opens THAT item and comments on it, exactly the
            # reach a reporter has, and nothing wider. comment.write's
            # qualifier names a relation to the parent ITEM (see the comments
            # item binding), so @own here is "on issues they reported" — the
            # first reporter gets the same discussion right the second one does.
            "item.read@participant",
            "comment.write@own",
            "comment.write@participant",
            # RADD-816 (Q4): the author-own rights, as grants — explainable in
            # the inspector and REVOCABLE, which the hardcoded checks never were.
            "comment.delete@own",
            "worklog.delete@own",
            "attachment.delete@own",
            # RADD-816 (F6): the catalog reads everyone had via the member
            # floor, now deliverable atoms — same day-one behaviour, revocable.
            Permission.LABEL_READ,
            Permission.CYCLE_READ,
            Permission.CANNED_READ,
            Permission.TEAM_READ,
            Permission.ROLE_READ,
            Permission.CARD_PRESET_READ,
        ),
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
            Permission.VIEW_CREATE,
            Permission.VIEW_UPDATE,
            Permission.VIEW_DELETE,
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
    BuiltinRole(
        key=BuiltinRoleKey.REQUESTER,
        name="Requester",
        description=(
            "The floor for email-provisioned requester accounts (never the "
            "Baseline): their own tickets, commenting and attaching on them, "
            "and nothing else — not other items, not the wiki."
        ),
        # item.read@own is the whole visibility story: every child surface
        # (comments, attachments, history) inherits it through the item seam,
        # and comment.write/attachment.create only reach items they can read.
        # @participant (RADD-844): a requester shared into a colleague's ticket
        # follows it like a second reporter — same floor shape as the Baseline.
        permissions=(
            "item.read@own",
            "item.read@participant",
            Permission.COMMENT_WRITE,
            Permission.ATTACHMENT_CREATE,
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
        # item.read@public is the whole story: the relation is a property of
        # the ROW (spec 121 §3), so internal and restricted issues never
        # reach the world however the project is shared. Comments ride the
        # item seam and internal ones need comment.read_internal, which is
        # not here; attachments are default-open behind the parent read.
        permissions=(
            "item.read@public",
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
        permissions=(
            Permission.ITEM_CREATE,
            "item.update@own",
            Permission.COMMENT_WRITE,
            Permission.ATTACHMENT_CREATE,
        ),
        position=5,
    ),
)



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
    GLOBAL_GRANT = "global_role_grant"  # spec 87 — instance-wide role assignment


class UserChange(StrEnum):
    """`action` values in user.updated event payloads."""

    PROFILE_UPDATED = "profile_updated"  # self-service name/avatar/timezone (spec 34)
    ADMIN_UPDATED = "admin_updated"  # PATCH /users/{id}: active/name by an instance admin (spec 84)
    DIRECTORY_DEACTIVATED = "directory_deactivated"  # spec 85 user sync: gone from the directory
