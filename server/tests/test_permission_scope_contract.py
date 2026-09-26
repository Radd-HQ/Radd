"""Every permission scope the server serves must be one the SPA declares, and
vice versa (RADD-808: the SPA never learned RADD-791's SPACE scope, so the roles
matrix silently dropped the page atoms). Atoms and scopes are strings on the
wire; no compiler catches this, so the test reads what the client declares."""

import re
from pathlib import Path

import pytest

from radd.modules.auth.types import PermissionScope

_WEB = Path(__file__).resolve().parents[2] / "web" / "src"
_TYPES = _WEB / "lib" / "types" / "permissions.ts"
_MATRIX = _WEB / "components" / "settings" / "PermissionMatrix.tsx"


def _declared_scopes() -> set[str]:
    """The scope values the SPA's `PermissionScope` const declares."""
    body = _TYPES.read_text()
    block = re.search(r"export const PermissionScope = \{(.*?)\n\} as const;", body, re.S)
    assert block, f"could not find the PermissionScope const in {_TYPES}"
    return set(re.findall(r'^\s*(?:/\*.*?\*/\s*)?\w+:\s*"([^"]+)"', block.group(1), re.M))


@pytest.mark.skipif(not _TYPES.exists(), reason="SPA sources not present in this checkout")
def test_every_server_scope_is_declared_by_the_spa() -> None:
    declared = _declared_scopes()
    missing = {s.value for s in PermissionScope} - declared
    assert not missing, (
        f"{sorted(missing)} exist on the server but not in {_TYPES.name}. "
        "Atoms carrying these scopes are dropped from the roles matrix silently."
    )


@pytest.mark.skipif(not _MATRIX.exists(), reason="SPA sources not present in this checkout")
def test_the_matrix_never_filters_by_scope() -> None:
    """RADD-815 regrouped the matrix by RESOURCE: every catalog atom renders
    unconditionally, so the RADD-808 class (a scope value with no bucket
    silently dropping its atoms) is impossible STRUCTURALLY. This pins that —
    a scope-based filter reappearing in the matrix is the regression."""
    source = _MATRIX.read_text()
    assert "byResource(catalog)" in source, (
        f"{_MATRIX.name} no longer groups the whole catalog by resource — "
        "if grouping filters again, dropped atoms become ungrantable invisibly."
    )
    assert ".scope ===" not in source and "filter((permission) => permission.scope" not in source, (
        f"{_MATRIX.name} filters by scope again — the RADD-808 regression."
    )


@pytest.mark.skipif(not _TYPES.exists(), reason="SPA sources not present in this checkout")
def test_the_spa_declares_no_scope_the_server_cannot_emit() -> None:
    """The other direction: a client-only scope is dead UI that reads as supported."""
    known = {s.value for s in PermissionScope}
    invented = _declared_scopes() - known
    assert not invented, (
        f"{sorted(invented)} are declared in {_TYPES.name} but are not a PermissionScope "
        "member. Either the server dropped a scope or the client invented one."
    )


def test_the_page_atoms_are_space_scoped() -> None:
    """The specific regression: RADD-791's move, pinned.

    Without this, restoring the atoms to GLOBAL would put the matrix back to
    green while reintroducing the bug the scope was created to fix.
    """
    from radd.modules.auth.types import Permission, permission_scope_of

    for atom in (Permission.PAGE_READ, Permission.PAGE_WRITE, Permission.PAGE_MANAGE):
        assert permission_scope_of(atom) is PermissionScope.SPACE, (
            f"{atom} is not SPACE-scoped; per-space access depends on it (RADD-791)."
        )


def test_plugin_permission_spec_scopes_parse():
    """RADD-818: PermissionSpec.scope documented "project|global|instance" while
    RADD-791 added "space" — this pins the vocabulary to the enum, so the drift
    class (RADD-808, one layer up) cannot recur silently."""
    from radd.kernel import registries
    from radd.modules.auth.types import PermissionScope

    for spec in registries.permissions.values():
        PermissionScope(spec.scope)  # raises on drifted vocabulary
    # And the documented set IS the enum, so the docstring cannot lie quietly.
    assert {s.value for s in PermissionScope} == {"project", "global", "space"}
