"""RBAC registries are plugin-contributable (spec 93 / A2 + north-star A10).

A plugin declares CRUD resources + standalone atoms in its manifest; they must
appear in the permission catalog / all_permission_keys, imply correctly under an
umbrella, be held by admin, and be grantable in a role — with ZERO edits to auth.
Pure/in-memory: exercises the merged-view accessors + the schema validator.
"""

import pytest

from radd.kernel import CrudResourceSpec, PermissionSpec, RaddPlugin, registries
from radd.modules.auth import authz
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import (
    PermissionScope,
    all_permission_keys,
    expand_permissions,
    permission_description_of,
    permission_scope_of,
)


@pytest.fixture
def milestones_plugin():
    """Register a milestones-like plugin's RBAC contributions (conftest reloaded
    the builtins first, so this layers on top)."""
    registries.register_plugin(
        RaddPlugin(
            name="test_milestones",
            id="radd.test_milestones",
            core=False,
            crud_resources=(
                CrudResourceSpec("milestone", "global", "milestones", "milestone.manage"),
            ),
            permissions=(PermissionSpec("milestone.publish", "global", "Publish a milestone"),),
        )
    )
    yield


def test_registered_atoms_appear_in_the_catalog(milestones_plugin):
    keys = all_permission_keys()
    for atom in ("milestone.create", "milestone.update", "milestone.delete",
                 "milestone.manage", "milestone.publish"):
        assert atom in keys, atom
    assert permission_scope_of("milestone.create") is PermissionScope.GLOBAL
    assert "milestones" in permission_description_of("milestone.create").lower()
    assert permission_description_of("milestone.publish") == "Publish a milestone"


def test_umbrella_implies_registered_crud_atoms(milestones_plugin):
    expanded = expand_permissions({"milestone.manage"})
    assert {"milestone.create", "milestone.update", "milestone.delete"} <= expanded


def test_admin_holds_registered_atoms(milestones_plugin):
    admin = authz.combine_permissions(instance_role="admin", permission_sets=[])
    assert "milestone.create" in admin
    assert "milestone.publish" in admin


def test_role_can_grant_a_registered_atom(milestones_plugin):
    role = RoleCreate(key="release-mgr", name="Release Manager",
                      permissions=["milestone.create", "milestone.publish", "item.read"])
    assert "milestone.publish" in role.permissions
    # a member holding it passes the union
    granted = authz.combine_permissions(
        instance_role="member", permission_sets=[role.permissions]
    )
    assert "milestone.create" in granted


def test_unknown_atom_still_rejected(milestones_plugin):
    with pytest.raises(ValueError):
        RoleCreate(key="bad", name="Bad", permissions=["totally.bogus"])


def test_no_registered_plugin_means_builtins_only():
    # Without the fixture: all_permission_keys == the builtin enum set exactly.
    from radd.modules.auth.types import Permission

    assert all_permission_keys() == frozenset(p.value for p in Permission)
