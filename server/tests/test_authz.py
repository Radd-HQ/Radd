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
from radd.modules.auth.authz import (
    ALL_PERMISSIONS,
    MEMBER_FLOOR,
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


def patch_lookups(monkeypatch, *, permission_sets=(), global_permission_sets=()):
    """Two DB lookups to stub: the per-project role grants, and (spec 87) the
    instance-wide ones. Admin is instance_role and the member floor needs no
    query, so nothing else touches the session."""

    async def fake_permission_sets(session, user_id, project):
        return [list(permissions) for permissions in permission_sets]

    async def fake_global_permission_sets(session, user_id):
        return [list(permissions) for permissions in global_permission_sets]

    monkeypatch.setattr(authz, "_project_permission_sets", fake_permission_sets)
    monkeypatch.setattr(authz, "_global_permission_sets", fake_global_permission_sets)


# --- builtin role definitions (global, immutable rows) ---


def test_builtin_admin_holds_every_project_scoped_permission():
    admin = set(builtin_role(BuiltinRoleKey.ADMIN).permissions)
    # Every project-scoped atom, plus dashboard.create as a global-scoped rider
    # (spec 75 — the doc.write-on-member precedent). Spec 87 dropped the
    # update/delete riders with their atoms: dashboards decide those by
    # ownership, so no atom was ever consulted.
    assert admin == set(PROJECT_PERMISSIONS) | {Permission.DASHBOARD_CREATE}
    assert {
        Permission.PROJECT_MANAGE,
        Permission.VIEW_MANAGE,
        Permission.COMMENT_READ_INTERNAL,
    } <= admin
    # No admin-tier global permissions leak into a project role.
    assert not admin & {Permission.GLOBAL_MANAGE, Permission.ROLE_MANAGE, Permission.TEAM_MANAGE}


def test_builtin_member_and_viewer_sets():
    assert set(builtin_role(BuiltinRoleKey.MEMBER).permissions) == {
        Permission.ITEM_READ,
        Permission.ITEM_CREATE,
        Permission.ITEM_UPDATE,
        Permission.WORKLOG_WRITE,  # members log their own time (spec 22)
        Permission.COMMENT_WRITE,
        Permission.COMMENT_READ_INTERNAL,
        Permission.VIEW_MANAGE,
        Permission.FORM_MANAGE,  # members author intake forms (spec 36)
        Permission.DOC_WRITE,  # members write docs (spec 43)
    }
    assert set(builtin_role(BuiltinRoleKey.VIEWER).permissions) == {
        Permission.ITEM_READ,
        Permission.DOC_READ,  # the wiki-read floor rider (spec 43)
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
        Permission.RELEASE_MANAGE,
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
    doc = {Permission.DOC_READ, Permission.DOC_WRITE, Permission.DOC_MANAGE}
    viewer = set(builtin_role(BuiltinRoleKey.VIEWER).permissions)
    member = set(builtin_role(BuiltinRoleKey.MEMBER).permissions)
    admin = set(builtin_role(BuiltinRoleKey.ADMIN).permissions)
    assert (viewer - doc) < (member - doc) < (admin - doc)
    assert viewer & doc == {Permission.DOC_READ}
    assert member & doc == {Permission.DOC_WRITE}


def test_every_builtin_key_is_defined_once():
    assert [role.key for role in BUILTIN_ROLES] == list(BuiltinRoleKey)


def test_permission_catalog_is_total():
    # Every permission has a scope and a description (GET /permissions renders these).
    assert set(PERMISSION_SCOPES) == set(Permission)
    assert set(PERMISSION_DESCRIPTIONS) == set(Permission)
    assert all(isinstance(scope, PermissionScope) for scope in PERMISSION_SCOPES.values())
    assert all(PERMISSION_DESCRIPTIONS[p] for p in Permission)


def test_member_floor_is_the_builtin_viewer_set():
    assert MEMBER_FLOOR == frozenset(builtin_role(BuiltinRoleKey.VIEWER).permissions)


# --- pure decision core ---


def test_combine_unions_across_role_sets_plus_member_floor():
    combined = combine_permissions(
        instance_role=InstanceRole.MEMBER,
        permission_sets=[[Permission.ITEM_UPDATE], [Permission.COMMENT_WRITE]],
    )
    assert combined == {
        Permission.ITEM_READ,  # the floor
        Permission.DOC_READ,  # rides the floor via the viewer set (spec 43)
        Permission.ITEM_UPDATE,
        Permission.COMMENT_WRITE,
    }


def test_combine_custom_role_grants_its_permissions_plus_the_member_floor():
    # Spec 86: every active user holds the member floor, so a custom role's
    # grants ride ON TOP of the viewer floor — never below it.
    combined = combine_permissions(
        instance_role=InstanceRole.MEMBER, permission_sets=[TRIAGER]
    )
    assert combined == set(TRIAGER) | MEMBER_FLOOR
    assert Permission.ITEM_CREATE not in combined


def test_combine_no_grants_is_the_member_floor():
    # An active user with no project grants still holds the floor (spec 86 —
    # being an active user of the server IS membership).
    assert (
        combine_permissions(instance_role=InstanceRole.MEMBER, permission_sets=[])
        == MEMBER_FLOOR
    )


def test_combine_instance_admin_gets_everything():
    assert (
        combine_permissions(instance_role=InstanceRole.ADMIN, permission_sets=[])
        == ALL_PERMISSIONS
    )


def test_global_scope_permissions():
    assert global_scope_permissions(InstanceRole.ADMIN.value) == ALL_PERMISSIONS
    # Spec 36: members additionally run cycles + see timesheets at global
    # scope; spec 43 adds writing docs. Spec 50: cycle.manage expands to its
    # create/update/delete atoms so the granular cycle endpoints resolve.
    member = global_scope_permissions(InstanceRole.MEMBER.value)
    assert member == expand_permissions(
        MEMBER_FLOOR
        | {Permission.CYCLE_MANAGE, Permission.TIMESHEET_VIEW, Permission.DOC_WRITE}
    )
    assert {
        Permission.CYCLE_CREATE,
        Permission.CYCLE_UPDATE,
        Permission.CYCLE_DELETE,
    } <= member
    assert global_scope_permissions(None) == frozenset()  # inactive
    assert Permission.ROLE_MANAGE in global_scope_permissions(InstanceRole.ADMIN.value)
    assert Permission.ROLE_MANAGE not in member


# --- effective_permissions (lookups stubbed) — spec 86 semantics ---


async def test_effective_instance_admin_skips_lookups():
    # No patched lookup: an instance admin must short-circuit before any query.
    permissions = await effective_permissions(
        SESSION, StubUser(InstanceRole.ADMIN), project=StubProject()
    )
    assert permissions == ALL_PERMISSIONS


async def test_effective_union_of_direct_team_and_floor(monkeypatch):
    # Any ACTIVE user holds the member floor — no membership row involved.
    patch_lookups(monkeypatch, permission_sets=[TRIAGER, [Permission.ITEM_CREATE]])
    permissions = await effective_permissions(SESSION, StubUser(), project=StubProject())
    assert permissions == set(TRIAGER) | {Permission.ITEM_CREATE, Permission.DOC_READ}


async def test_effective_inactive_user_has_no_permissions(monkeypatch):
    patch_lookups(monkeypatch)
    user = StubUser(active=False)
    assert await effective_permissions(SESSION, user, project=StubProject()) == frozenset()
    assert await effective_permissions(SESSION, user) == frozenset()


# --- require ---


async def test_require_instance_admin_passes_everywhere():
    admin = StubUser(InstanceRole.ADMIN)
    assert await require(SESSION, admin, Permission.USER_MANAGE) == ALL_PERMISSIONS
    assert await require(SESSION, admin, Permission.TEAM_MANAGE) == ALL_PERMISSIONS
    assert (
        await require(SESSION, admin, Permission.PROJECT_MANAGE, project=StubProject())
        == ALL_PERMISSIONS
    )


async def test_require_returns_the_effective_union(monkeypatch):
    patch_lookups(monkeypatch, permission_sets=[[Permission.ITEM_READ, Permission.ITEM_CREATE]])
    permissions = await require(SESSION, StubUser(), Permission.ITEM_CREATE, project=StubProject())
    # The active-user floor (viewer set) rides along with the granted role.
    assert permissions == {Permission.ITEM_READ, Permission.ITEM_CREATE, Permission.DOC_READ}


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
    # An active user with NO project grants: floor reads pass, writes 403.
    patch_lookups(monkeypatch)
    user, project = StubUser(), StubProject()
    assert Permission.ITEM_READ in await require(
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
        await require(SESSION, StubUser(InstanceRole.ADMIN), Permission.ROLE_MANAGE)
        == ALL_PERMISSIONS
    )
    with pytest.raises(ForbiddenError):
        await require(SESSION, StubUser(), Permission.ROLE_MANAGE)
    assert Permission.ITEM_READ in await require(SESSION, StubUser(), Permission.ITEM_READ)


async def test_require_unscoped_member_floor_and_admin_tier(monkeypatch):
    patch_lookups(monkeypatch)
    assert Permission.USER_MANAGE in await require(
        SESSION, StubUser(InstanceRole.ADMIN), Permission.USER_MANAGE
    )
    assert Permission.ITEM_READ in await require(SESSION, StubUser(), Permission.ITEM_READ)
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
