"""Every RBAC atom is declared by the module that enforces it (RADD-890).

`auth/types.py::Permission` used to enumerate every feature module's atoms —
`item.*`, `page.*`, `worklog.*`, `sla.*`, `vcsconn.*` — so adding a permission
anywhere meant editing auth, while the kernel permissions registry that exists
for exactly that had one client (`milestones`). Two parallel systems: plugins
contributed, core modules edited auth.

The registry is the catalog now, and the enum is the typed alias surface call
sites hold. That split is only safe while the two agree, so this file asserts
BOTH directions:

  - registry ⊇ enum: every atom has an owner, with the same scope auth records.
  - registry ⊆ enum: nothing is contributed that the alias cannot name (the
    thing that lets `Permission.ITEM_READ` keep working unchanged).

Plus the ownership rule itself: auth declares governance atoms only. An atom
added to auth's manifest that belongs to a feature fails here, which is the
regression this issue exists to prevent.

Pure/in-memory — reads the registry conftest's autouse fixture loads.
"""

from radd.kernel import registries
from radd.modules.auth.permissions import AUTH_CRUD_RESOURCES, AUTH_PERMISSIONS
from radd.modules.auth.types import (
    PERMISSION_SCOPES,
    Permission,
    PermissionScope,
    all_permission_keys,
    permission_description_of,
    permission_scope_of,
)

#: What auth is allowed to declare: the two umbrellas, project creation, and the
#: four resources whose tables and routers live in auth. Anything else is some
#: feature's atom and belongs on that feature's manifest.
AUTH_OWNED = {
    "global.manage",
    "project.create",
    "project.manage",
    "project.delete",
    "user.manage", "user.create", "user.update", "user.delete",
    "role.read", "role.create", "role.update", "role.delete",
    "member.create", "member.update", "member.delete",
    "service_account.create", "service_account.update",
}


def _declared() -> dict[str, set[str]]:
    """atom -> the plugins that declare it, over the loaded registry."""
    out: dict[str, set[str]] = {}
    for plugin in registries.plugins.values():
        for spec in plugin.permissions:
            out.setdefault(spec.key, set()).add(plugin.name)
        for crud in plugin.crud_resources:
            for action in crud.actions:
                out.setdefault(f"{crud.key}.{action}", set()).add(plugin.name)
    return out


def test_every_atom_has_an_owning_module():
    """enum ⊆ registry. An atom added to the alias alone has no scope, no
    description and no owner — it would appear in the roles matrix as a blank
    row and refuse with a sentence nobody wrote."""
    declared = _declared()
    orphans = sorted(p.value for p in Permission if p.value not in declared)
    assert not orphans, (
        "atoms in auth.types.Permission that no plugin declares — put each on the "
        "manifest of the module that enforces it:\n  " + "\n  ".join(orphans)
    )


def test_no_atom_has_two_owners():
    """One declaration per atom. Two modules claiming `item.read` means two
    descriptions, and which one the catalog shows is dict-ordering luck."""
    shared = {k: sorted(v) for k, v in _declared().items() if len(v) > 1}
    assert not shared, f"atoms declared by more than one plugin: {shared}"


def test_declared_scopes_match_auth_s_import_time_table():
    """`_PROJECT_SCOPED`/`_SPACE_SCOPED` in auth are the ONE fact auth still has
    to know before the loader runs (PROJECT_PERMISSIONS, and through it the
    seeded Admin role, is computed at import). This is what stops that copy from
    drifting from the owning module's declaration."""
    mismatches = []
    for plugin in registries.plugins.values():
        for spec in plugin.permissions:
            declared = PermissionScope(spec.scope)
            recorded = PERMISSION_SCOPES.get(spec.key)  # type: ignore[arg-type]
            if recorded is not None and recorded is not declared:
                mismatches.append(f"{spec.key}: {plugin.name} says {declared}, auth says {recorded}")
        for crud in plugin.crud_resources:
            declared = PermissionScope(crud.scope)
            for action in crud.actions:
                atom = f"{crud.key}.{action}"
                recorded = PERMISSION_SCOPES.get(atom)  # type: ignore[arg-type]
                if recorded is not None and recorded is not declared:
                    mismatches.append(
                        f"{atom}: {plugin.name} says {declared}, auth says {recorded}"
                    )
    assert not mismatches, "scope drift between a module and auth:\n  " + "\n  ".join(mismatches)


def test_registry_adds_no_atom_the_alias_cannot_name():
    """registry ⊆ enum, for the CORE set. This is what keeps every
    `Permission.X` call site working: an atom contributed by a bootstrap module
    with no enum member would be enforceable and unnameable in Python."""
    assert all_permission_keys() == frozenset(p.value for p in Permission)


def test_auth_declares_only_governance_atoms():
    auth_atoms = {spec.key for spec in AUTH_PERMISSIONS}
    for crud in AUTH_CRUD_RESOURCES:
        auth_atoms |= {f"{crud.key}.{action}" for action in crud.actions}
    assert auth_atoms == AUTH_OWNED, (
        "auth's manifest drifted from the governance set. Feature atoms belong "
        f"on the feature's manifest.\n  extra: {sorted(auth_atoms - AUTH_OWNED)}"
        f"\n  missing: {sorted(AUTH_OWNED - auth_atoms)}"
    )


def test_every_atom_reads_as_a_sentence():
    """Scope and prose both resolve through the registry for every atom — this
    is what `GET /permissions` renders, so a blank one is a blank matrix row."""
    for permission in Permission:
        assert isinstance(permission_scope_of(permission), PermissionScope), permission
        description = permission_description_of(permission)
        assert description and description.endswith("."), f"{permission}: {description!r}"


def test_umbrellas_expand_through_the_registry():
    """The implication edges moved out of auth with the atoms: a CRUD resource's
    `manage`, a `PermissionSpec.implied_by`, and `.implies` for the qualified
    form `implied_by` cannot express (RADD-790's `attachment.delete@own`)."""
    from radd.modules.auth.types import IMPLIED_PERMISSIONS, expand_permissions, implied_map

    assert not IMPLIED_PERMISSIONS, "auth owns no implications; they are module declarations now"
    assert {"state.manage", "field.manage", "release.create", "member.delete"} <= implied_map()[
        "project.manage"
    ]
    assert implied_map()["page.manage"] == frozenset({"page.delete"})
    assert {"attachment.create", "attachment.delete@own"} <= expand_permissions({"item.update"})
    # …and the qualified form is an implication, never a catalog atom.
    assert "attachment.delete@own" not in all_permission_keys()
