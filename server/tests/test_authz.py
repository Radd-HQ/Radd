"""Unit tests for the RBAC seam (auth/authz.py) — data-driven roles, spec 06/86.

The decision core is pure (no DB); `require`/`effective_permissions` are exercised by
monkeypatching the per-project role-grant lookup. Role-mutation guards (immutable
builtins, delete rules) are pure functions in auth/roles.py, tested with stub rows.

Spec 86: the workspace entity is gone — admin is `users.instance_role == admin`,
any ACTIVE user holds the builtin member floor, inactive users hold nothing.
"""

import uuid

import pytest

from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.auth import authz, roles
from radd.modules.auth.types import all_permission_keys
from radd.modules.auth.authz import (
    Permission,
    combine_permissions,
    effective_permissions,
    expand_permissions,
    require,
    global_scope_permissions,
)
from radd.modules.auth.types import (
    BUILTIN_ROLES,
    PERMISSION_DESCRIPTIONS,
    PERMISSION_SCOPES,
    PROJECT_PERMISSIONS,
    BuiltinRoleKey,
    InstanceRole,
    PermissionScope,
    builtin_role,
)


class StubUser:
    """Duck-types auth.models.User for the seam (id/instance_role/active)."""

    def __init__(self, instance_role: InstanceRole = InstanceRole.MEMBER, active: bool = True):
        self.id = uuid.uuid4()
        self.instance_role = instance_role.value
        self.active = active


class StubProject:
    """Duck-types projects.models.Project (id, key)."""

    def __init__(self):
        self.id = uuid.uuid4()
        self.key = "TD"


class StubRole:
    """Duck-types auth.models.Role for the pure mutation guards."""

    def __init__(self, key="triager", is_builtin=False):
        self.key = key
        self.is_builtin = is_builtin


SESSION = object()  # never touched once the lookup is patched

TRIAGER = [Permission.ITEM_READ, Permission.ITEM_UPDATE, Permission.COMMENT_WRITE]
#: What `item.update` drags in (RADD-790) — spelled out so the expectations below
#: read as "the role's atoms plus what they imply" rather than a magic pair.
# RADD-816: item.update implies attaching + deleting YOUR OWN attachments —
# the unqualified delete verb means anyone's now and rides project.manage.
ATTACHING = {Permission.ATTACHMENT_CREATE, "attachment.delete@own"}


def patch_lookups(monkeypatch, *, permission_sets=(), global_permission_sets=(), baseline=None):
    """THREE DB lookups to stub: the per-project role grants, (spec 87) the
    instance-wide ones, and (RADD-773) the Baseline role's permissions.

    That third one is new, and it is the change in a sentence: the floor used to
    be a constant that needed no query, and is now a row an admin can edit.
    `baseline=` defaults to the seeded set so these tests describe a stock
    instance; pass your own to model an admin who has retuned it.
    """

    async def fake_permission_sets(session, user_id, project):
        return [list(permissions) for permissions in permission_sets]

    async def fake_global_permission_sets(session, user_id):
        return [list(permissions) for permissions in global_permission_sets]

    seeded = frozenset(builtin_role(BuiltinRoleKey.BASELINE).permissions)

    async def fake_baseline(session):
        return seeded if baseline is None else frozenset(baseline)

    monkeypatch.setattr(authz, "_project_permission_sets", fake_permission_sets)
    monkeypatch.setattr(authz, "_global_permission_sets", fake_global_permission_sets)
    monkeypatch.setattr(authz, "baseline_permissions", fake_baseline)


# --- builtin role definitions (global, immutable rows) ---


def test_builtin_admin_holds_every_project_scoped_permission():
    admin = set(builtin_role(BuiltinRoleKey.ADMIN).permissions)
    # Every project-scoped atom, plus dashboard.create as a global-scoped rider
    # (spec 75 — the page.write-on-member precedent). Spec 87 dropped the
    # update/delete riders with their atoms: dashboards decide those by
    # ownership, so no atom was ever consulted.
    assert admin == set(PROJECT_PERMISSIONS) | {Permission.DASHBOARD_CREATE}
    assert {
        Permission.PROJECT_MANAGE,
        Permission.VIEW_CREATE,
        Permission.COMMENT_READ_INTERNAL,
    } <= admin
    # No admin-tier global permissions leak into a project role.
    assert not admin & {Permission.GLOBAL_MANAGE, Permission.ROLE_CREATE, Permission.TEAM_CREATE}


def test_builtin_member_and_viewer_sets():
    assert set(builtin_role(BuiltinRoleKey.MEMBER).permissions) == {
        Permission.ITEM_READ,
        Permission.ITEM_CREATE,
        Permission.ITEM_UPDATE,
        Permission.WORKLOG_WRITE,  # members log their own time (spec 22)
        Permission.COMMENT_WRITE,
        Permission.COMMENT_READ_INTERNAL,
        Permission.VIEW_CREATE,
        Permission.VIEW_UPDATE,  # RADD-816: view.manage's job, as its triple
        Permission.VIEW_DELETE,
        Permission.FORM_MANAGE,  # members author intake forms (spec 36)
        Permission.PAGE_WRITE,  # members write docs (spec 43)
    }
    assert set(builtin_role(BuiltinRoleKey.VIEWER).permissions) == {
        Permission.ITEM_READ,
        Permission.PAGE_READ,  # the wiki-read floor rider (spec 43)
    }


def test_umbrellas_imply_per_entity_actions():
    # Spec 36: a role holding project.manage keeps full project control even
    # though states/releases/fields now check granular permissions.
    combined = combine_permissions(
        instance_role=InstanceRole.MEMBER,
        permission_sets=[[Permission.PROJECT_MANAGE]],
    )
    assert {
        Permission.STATE_MANAGE,
        Permission.RELEASE_CREATE,
        Permission.FIELD_MANAGE,
    } <= combined
    # And a granular grant alone does NOT imply the umbrella.
    granular = combine_permissions(
        instance_role=InstanceRole.MEMBER,
        permission_sets=[[Permission.STATE_MANAGE]],
    )
    assert Permission.PROJECT_MANAGE not in granular


def test_manage_umbrellas_expand_to_crud_atoms_transitively():
    # Spec 50: project.manage resolves, in one expansion pass, to the granular
    # create/update/delete atoms of every project resource — including the
    # transitive chain project.manage -> state.manage -> state.create/update/delete.
    combined = combine_permissions(
        instance_role=InstanceRole.MEMBER,
        permission_sets=[[Permission.PROJECT_MANAGE]],
    )
    assert {
        Permission.STATE_CREATE,
        Permission.STATE_UPDATE,
        Permission.STATE_DELETE,
        Permission.FIELD_CREATE,
        Permission.RELEASE_DELETE,
        Permission.MEMBER_CREATE,
        Permission.MEMBER_DELETE,
        Permission.ITEM_DELETE,
        Permission.COMMENT_DELETE,
        Permission.WORKLOG_DELETE,
    } <= combined
    # A single granular atom confers neither its siblings nor the umbrella.
    only_create = combine_permissions(
        instance_role=InstanceRole.MEMBER,
        permission_sets=[[Permission.STATE_CREATE]],
    )
    assert Permission.STATE_DELETE not in only_create
    assert Permission.STATE_MANAGE not in only_create
    assert Permission.PROJECT_MANAGE not in only_create


def test_builtin_sets_are_strictly_nested():
    # Nesting holds over the PROJECT-scoped permissions. The doc permissions
    # (spec 43) are global-scoped riders on viewer/member — they feed the
    # member floor/scope sets, not the project hierarchy — so they're
    # excluded here and pinned separately.
    doc = {Permission.PAGE_READ, Permission.PAGE_WRITE, Permission.PAGE_MANAGE}
    viewer = set(builtin_role(BuiltinRoleKey.VIEWER).permissions)
    member = set(builtin_role(BuiltinRoleKey.MEMBER).permissions)
    admin = set(builtin_role(BuiltinRoleKey.ADMIN).permissions)
    assert (viewer - doc) < (member - doc) < (admin - doc)
    assert viewer & doc == {Permission.PAGE_READ}
    assert member & doc == {Permission.PAGE_WRITE}


def test_every_builtin_key_is_defined_once():
    assert [role.key for role in BUILTIN_ROLES] == list(BuiltinRoleKey)


def test_permission_catalog_is_total():
    # Every permission has a scope and a description (GET /permissions renders these).
    assert set(PERMISSION_SCOPES) == set(Permission)
    assert set(PERMISSION_DESCRIPTIONS) == set(Permission)
    assert all(isinstance(scope, PermissionScope) for scope in PERMISSION_SCOPES.values())
    assert all(PERMISSION_DESCRIPTIONS[p] for p in Permission)


#: The seeded Baseline set (RADD-773) — item.read + page.read. The tests below
#: pass it EXPLICITLY, because that is now the contract: the combiners take the
#: baseline as an argument and hold no opinion of their own about it.
BASELINE = frozenset(builtin_role(BuiltinRoleKey.BASELINE).permissions)


def test_baseline_is_seeded_read_only():
    """The seed is a policy decision, so it is worth asserting rather than assuming.

    RADD-773 deliberately narrowed it: `page.write`, `cycle.manage` and
    `timesheet.view` used to be free for every active user via a second hardcoded
    set, which is how a member with no grants anywhere could edit any wiki page
    and delete any cycle. Anything beyond reading now has to be granted.
    """
    # RADD-816 widened the seed deliberately: the Q4 author-own rights and the
    # F6 catalog reads become GRANTS everyone holds — explainable and revocable
    # — instead of hardcoded checks and vacuous member-floor gates. RADD-825
    # (Q2) then narrowed the READS: item.read@OWN (your reported issues, via
    # the relation machinery) and no page.read at all — a floor page.read
    # defeated every restricted space (N5). Wider is a deliberate edit now.
    # RADD-844 added the second-reporter floor: a participant opens the shared
    # item and comments on it; @own on comment.write gives the FIRST reporter
    # the same discussion right.
    assert BASELINE == {
        "item.read@own",
        "item.read@participant",
        "comment.write@own",
        "comment.write@participant",
        "comment.delete@own",
        "worklog.delete@own",
        "attachment.delete@own",
        Permission.LABEL_READ,
        Permission.CYCLE_READ,
        Permission.CANNED_READ,
        Permission.TEAM_READ,
        Permission.ROLE_READ,
        Permission.CARD_PRESET_READ,
    }
    assert Permission.PAGE_WRITE not in BASELINE
    assert Permission.CYCLE_CREATE not in BASELINE
    assert Permission.TIMESHEET_VIEW not in BASELINE


def test_combiners_hold_no_opinion_without_a_baseline():
    """No baseline argument -> no floor. The default fails CLOSED.

    An absent Baseline row (a database mid-migration) must not silently
    reinstate the permissive floor this replaced, so the default is empty rather
    than the old viewer set.
    """
    assert combine_permissions(instance_role=InstanceRole.MEMBER, permission_sets=[]) == frozenset()
    assert global_scope_permissions(InstanceRole.MEMBER.value) == frozenset()


# --- pure decision core ---


def test_combine_unions_across_role_sets_plus_baseline():
    combined = combine_permissions(
        instance_role=InstanceRole.MEMBER,
        permission_sets=[[Permission.ITEM_UPDATE], [Permission.COMMENT_WRITE]],
        baseline=BASELINE,
    )
    # RADD-790/816: item.update implies attachment.create + delete@own; the
    # baseline rides along whole (incl. its @own grants + catalog reads).
    assert combined == expand_permissions(
        BASELINE | {Permission.ITEM_UPDATE, Permission.COMMENT_WRITE}
    )


def test_combine_custom_role_grants_its_permissions_plus_the_baseline():
    # A custom role's grants ride ON TOP of the baseline — never below it.
    combined = combine_permissions(
        instance_role=InstanceRole.MEMBER, permission_sets=[TRIAGER], baseline=BASELINE
    )
    # `| ATTACHING` because TRIAGER holds item.update, which implies it (RADD-790).
    assert combined == set(TRIAGER) | BASELINE | ATTACHING
    assert Permission.ITEM_CREATE not in combined


def test_combine_no_grants_is_the_baseline():
    # An active user with no project grants still holds the baseline (spec 86 —
    # being an active user of the server IS membership).
    assert (
        combine_permissions(
            instance_role=InstanceRole.MEMBER, permission_sets=[], baseline=BASELINE
        )
        == BASELINE
    )


def test_editing_the_baseline_changes_what_everyone_holds():
    """The point of the whole change: the floor is an argument, so an admin
    editing the Baseline row moves it. Under the old constants this was
    unexpressible — unchecking a permission anywhere left the floor untouched."""
    widened = combine_permissions(
        instance_role=InstanceRole.MEMBER,
        permission_sets=[],
        baseline=BASELINE | {Permission.VIEW_CREATE},
    )
    assert Permission.VIEW_CREATE in widened  # umbrella expansion still applies
    narrowed = combine_permissions(
        instance_role=InstanceRole.MEMBER, permission_sets=[], baseline={Permission.PAGE_READ}
    )
    assert Permission.ITEM_READ not in narrowed


def test_combine_instance_admin_gets_everything():
    assert (
        combine_permissions(instance_role=InstanceRole.ADMIN, permission_sets=[])
        == all_permission_keys()
    )


def test_global_scope_permissions():
    assert global_scope_permissions(InstanceRole.ADMIN.value) == all_permission_keys()
    # Spec 36: members additionally run cycles + see timesheets at global
    # scope; spec 43 adds writing docs. Spec 50: cycle.manage expands to its
    # create/update/delete atoms so the granular cycle endpoints resolve.
    # RADD-773: the same baseline feeds both scopes, and it no longer carries
    # cycle.manage / timesheet.view / page.write — those must be granted.
    member = global_scope_permissions(InstanceRole.MEMBER.value, baseline=BASELINE)
    assert member == expand_permissions(BASELINE)
    assert not {
        Permission.CYCLE_CREATE,
        Permission.CYCLE_UPDATE,
        Permission.CYCLE_DELETE,
        Permission.PAGE_WRITE,
        Permission.TIMESHEET_VIEW,
    } & member
    # Granted instance-wide, the umbrella still expands (spec 50).
    # RADD-816 deleted cycle.manage — global.manage is the umbrella that
    # expands to the cycle triple now.
    with_cycles = global_scope_permissions(
        InstanceRole.MEMBER.value, [[Permission.GLOBAL_MANAGE]], baseline=BASELINE
    )
    assert {
        Permission.CYCLE_CREATE,
        Permission.CYCLE_UPDATE,
        Permission.CYCLE_DELETE,
    } <= with_cycles
    assert global_scope_permissions(None) == frozenset()  # inactive
    assert Permission.ROLE_CREATE in global_scope_permissions(InstanceRole.ADMIN.value)
    assert Permission.ROLE_CREATE not in member


# --- effective_permissions (lookups stubbed) — spec 86 semantics ---


async def test_effective_instance_admin_skips_lookups():
    # No patched lookup: an instance admin must short-circuit before any query.
    permissions = await effective_permissions(
        SESSION, StubUser(InstanceRole.ADMIN), project=StubProject()
    )
    assert permissions == all_permission_keys()


async def test_effective_union_of_direct_team_and_floor(monkeypatch):
    # Any ACTIVE user holds the member floor — no membership row involved.
    patch_lookups(monkeypatch, permission_sets=[TRIAGER, [Permission.ITEM_CREATE]])
    permissions = await effective_permissions(SESSION, StubUser(), project=StubProject())
    assert permissions == expand_permissions(
        set(TRIAGER) | BASELINE | {Permission.ITEM_CREATE}
    )


async def test_effective_inactive_user_has_no_permissions(monkeypatch):
    patch_lookups(monkeypatch)
    user = StubUser(active=False)
    assert await effective_permissions(SESSION, user, project=StubProject()) == frozenset()
    assert await effective_permissions(SESSION, user) == frozenset()


# --- require ---


async def test_require_instance_admin_passes_everywhere():
    admin = StubUser(InstanceRole.ADMIN)
    assert await require(SESSION, admin, Permission.USER_MANAGE) == all_permission_keys()
    assert await require(SESSION, admin, Permission.TEAM_CREATE) == all_permission_keys()
    assert (
        await require(SESSION, admin, Permission.PROJECT_MANAGE, project=StubProject())
        == all_permission_keys()
    )


async def test_require_returns_the_effective_union(monkeypatch):
    patch_lookups(monkeypatch, permission_sets=[[Permission.ITEM_READ, Permission.ITEM_CREATE]])
    permissions = await require(SESSION, StubUser(), Permission.ITEM_CREATE, project=StubProject())
    # The active-user floor (the seeded Baseline) rides along with the role —
    # which since RADD-825 carries item.read@own; the FULL item.read comes from
    # the role set this test patched in.
    assert permissions == expand_permissions(
        BASELINE | {Permission.ITEM_READ, Permission.ITEM_CREATE}
    )


async def test_require_custom_role_allows_update_but_not_create(monkeypatch):
    # The spec-06 acceptance case: a "triager" can update items but not create them.
    patch_lookups(monkeypatch, permission_sets=[TRIAGER])
    user, project = StubUser(), StubProject()
    assert Permission.ITEM_UPDATE in await require(
        SESSION, user, Permission.ITEM_UPDATE, project=project
    )
    with pytest.raises(ForbiddenError):
        await require(SESSION, user, Permission.ITEM_CREATE, project=project)


async def test_require_floor_only_user_denied_writes(monkeypatch):
    # An active user with NO project grants: the floor's item.read@OWN passes
    # the GATE (holds_base — RADD-825 narrowed the floor; which rows they see
    # is the relation resolvers' question), writes 403.
    patch_lookups(monkeypatch)
    user, project = StubUser(), StubProject()
    assert "item.read@own" in await require(
        SESSION, user, Permission.ITEM_READ, project=project
    )
    with pytest.raises(ForbiddenError):
        await require(SESSION, user, Permission.ITEM_CREATE, project=project)
    with pytest.raises(ForbiddenError):
        await require(SESSION, user, Permission.PROJECT_MANAGE, project=project)


async def test_require_inactive_user_denied_even_reads(monkeypatch):
    patch_lookups(monkeypatch)
    user = StubUser(active=False)
    with pytest.raises(ForbiddenError):
        await require(SESSION, user, Permission.ITEM_READ, project=StubProject())
    with pytest.raises(ForbiddenError):
        await require(SESSION, user, Permission.ITEM_READ)


async def test_require_global_scope_admin_and_member(monkeypatch):
    # Global scope (no project): an instance admin holds every global atom; a
    # plain active member holds the member global set (ITEM_READ yes, ROLE_MANAGE no).
    patch_lookups(monkeypatch)
    assert (
        await require(SESSION, StubUser(InstanceRole.ADMIN), Permission.ROLE_CREATE)
        == all_permission_keys()
    )
    with pytest.raises(ForbiddenError):
        await require(SESSION, StubUser(), Permission.ROLE_CREATE)
    assert "item.read@own" in await require(SESSION, StubUser(), Permission.ITEM_READ)


async def test_require_unscoped_member_floor_and_admin_tier(monkeypatch):
    patch_lookups(monkeypatch)
    assert Permission.USER_MANAGE in await require(
        SESSION, StubUser(InstanceRole.ADMIN), Permission.USER_MANAGE
    )
    assert "item.read@own" in await require(SESSION, StubUser(), Permission.ITEM_READ)
    with pytest.raises(ForbiddenError):
        await require(SESSION, StubUser(), Permission.USER_MANAGE)


# --- role mutation guards (immutable builtins, delete rules) ---


def test_builtin_permission_sets_are_immutable():
    with pytest.raises(ConflictError):
        roles.ensure_permissions_mutable(StubRole(key="admin", is_builtin=True))
    roles.ensure_permissions_mutable(StubRole())  # custom role: fine


def test_role_delete_rules():
    with pytest.raises(ConflictError):
        roles.ensure_deletable(StubRole(key="viewer", is_builtin=True), referenced=False)
    with pytest.raises(ConflictError):
        roles.ensure_deletable(StubRole(), referenced=True)
    roles.ensure_deletable(StubRole(), referenced=False)  # custom + unreferenced: fine


# Field-level visibility moved to per-role/team grants (spec 07) — see test_field_grants.py.


# --- the member-floor people directory (RADD-769) ---------------------------


def test_user_directory_entry_exposes_no_administrative_fields():
    """The directory is safe because of its SHAPE, not because of a gate.

    `GET /users/directory` is open to anyone with an account — the finding
    behind RADD-769 is that naming a colleague is not an administrative act, and
    gating it on `user.manage` put a 403 on nearly every issue and page an
    ordinary member opened. What keeps that from becoming the admin directory in
    disguise is that this model carries none of what `UserRead` does.

    So this asserts the EXCLUSION, not the inclusion: adding `email` (or the
    instance role, or sign-in history) back onto the entry would publish it to
    every account in the instance, and would do it silently.

    REVISED (RADD-869): `source` moved to the exposed side. Which auth backend
    an account uses is not a secret the way an address is, and without it a
    picker rendered a service account exactly like a colleague — defeating the
    "never mistaken for a person" intent the service-accounts module states.
    """
    from radd.modules.auth.schemas import UserDirectoryEntry, UserRead

    exposed = set(UserDirectoryEntry.model_fields)
    assert exposed == {"id", "name", "active", "source", "avatar_color", "avatar_emoji"}
    administrative = {"email", "instance_role", "last_login_at", "timezone"}
    assert exposed & administrative == set()
    # The administrative shape still carries them: this is a split by audience,
    # not a trim — `GET /users` keeps both the fields and `user.manage`.
    assert administrative <= set(UserRead.model_fields)
