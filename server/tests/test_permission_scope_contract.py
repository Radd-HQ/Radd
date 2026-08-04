"""Every permission scope the server can serve must be one the SPA renders.

This file exists because the roles matrix quietly stopped showing the page
atoms. RADD-791 moved `page.read/write/manage/delete` from GLOBAL to a new
SPACE scope — the right call, since a page had no scope to be checked against
and per-space access was inexpressible without one. The server half was
complete: the enum, the catalog, `role_grants.space_id`, the grant UI.

The SPA's `PermissionScope` never learned the word. `PermissionMatrix` renders
by iterating its own scope list and filtering the catalog to each one, so the
four space-scoped rows matched no group and rendered nowhere: no error, no
empty state, no console warning. An admin opening Settings → Roles simply could
not see or grant the page permissions, and the only visible symptom was a user
who "should" have had access not having it (RADD-808).

Nothing could have caught it. The atoms are strings on the wire and the scope
is a string beside them; TypeScript types the field as the client's union and
casts the JSON into it without complaint. This is the same class as RADD-701's
renamed constants and RADD-761's shadowed route — a contract with no compiler
behind it — so it gets the same treatment: a test that reads what the client
actually declares, rather than a promise to remember.

The assertion runs in BOTH directions deliberately. A scope the client lacks is
invisible atoms; a scope the client lists that the server never emits is dead
UI that reads as supported. Both were true here at once.
"""

import re
from pathlib import Path

import pytest

from radd.modules.auth.types import PermissionScope

_WEB = Path(__file__).resolve().parents[2] / "web" / "src"
_TYPES = _WEB / "lib" / "types" / "permissions.ts"
_MATRIX = _WEB / "components" / "settings" / "PermissionMatrix.tsx"

#: RADD-814 retired the `instance` tier (zero atoms, no resolution branch) on
#: both sides at once, so nothing is exempt any more: every declared scope must
#: be populated, and every populated scope must be declared.
_UNPOPULATED: set[PermissionScope] = set()


def _declared_scopes() -> set[str]:
    """The scope values the SPA's `PermissionScope` const declares."""
    body = _TYPES.read_text()
    block = re.search(r"export const PermissionScope = \{(.*?)\n\} as const;", body, re.S)
    assert block, f"could not find the PermissionScope const in {_TYPES}"
    return set(re.findall(r'^\s*(?:/\*.*?\*/\s*)?\w+:\s*"([^"]+)"', block.group(1), re.M))


def _rendered_scopes() -> set[str]:
    """The scopes `PermissionMatrix` actually iterates.

    Declaring a scope is not rendering one: the matrix walks SCOPE_ORDER, so a
    value present in the type and absent from that array is exactly as invisible
    as it was before — which is the failure this test is named for.
    """
    body = _MATRIX.read_text()
    block = re.search(r"const SCOPE_ORDER = \[(.*?)\] as const;", body, re.S)
    assert block, f"could not find SCOPE_ORDER in {_MATRIX}"
    return set(re.findall(r"PermissionScope\.(\w+)", block.group(1)))


@pytest.mark.skipif(not _TYPES.exists(), reason="SPA sources not present in this checkout")
def test_every_server_scope_is_declared_by_the_spa() -> None:
    declared = _declared_scopes()
    missing = {s.value for s in PermissionScope} - declared
    assert not missing, (
        f"{sorted(missing)} exist on the server but not in {_TYPES.name}. "
        "Atoms carrying these scopes are dropped from the roles matrix silently."
    )


@pytest.mark.skipif(not _MATRIX.exists(), reason="SPA sources not present in this checkout")
def test_every_server_scope_is_rendered_by_the_matrix() -> None:
    rendered = _rendered_scopes()
    missing = {s.name.lower() for s in PermissionScope} - rendered
    assert not missing, (
        f"{sorted(missing)} are declared but absent from SCOPE_ORDER in {_MATRIX.name}, "
        "so their atoms render nowhere and cannot be granted."
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
