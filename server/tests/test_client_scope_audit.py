"""RADD-810 — the client-gate scope audit, as a test.

Every `perms.global(Permission.X)` in the SPA where X is not a GLOBAL-scope
atom is the RADD-808/810 failure shape: a holder of the atom at its real scope
fails a global question, so the control silently vanishes for exactly the
people it was built for. The ten shipped instances are fixed (space-scoped
sites resolve against their space via RADD-814's `can({space})` leg,
project-scoped ones against the project in context or `anyProject`); the four
that are DELIBERATELY global — space-creation gates matching `create_space`'s
own no-space check — carry a `deliberately-global` marker comment.

This test re-runs the audit on every suite run: a new unannotated mismatch
fails with the file:line, and an annotation without a mismatch is flagged too
(a stale marker invites the next person to copy it). Same family as
`test_route_shadowing.py` and `test_permission_scope_contract.py` — a contract
with no compiler behind it gets a test or it rots.
"""

import re
from pathlib import Path

from radd.modules.auth.types import PermissionScope, permission_scope_of

_WEB = Path(__file__).resolve().parents[2] / "web" / "src"
_TYPES = _WEB / "lib" / "types" / "permissions.ts"

_MARKER = "deliberately-global"
#: How many lines above a call site the marker comment may sit (JSX block
#: comments span a few lines).
_MARKER_REACH = 8


def _client_atoms() -> dict[str, str]:
    """The SPA's Permission const: {constName: atom string}."""
    body = _TYPES.read_text()
    block = re.search(r"export const Permission = \{(.*?)\n\} as const;", body, re.S)
    assert block, f"could not find the Permission const in {_TYPES}"
    return dict(re.findall(r'(\w+):\s*"([^"]+)"', block.group(1)))


def _global_call_sites() -> list[tuple[Path, int, str, list[str]]]:
    """(file, line-no, const-name, preceding-lines) for every `.global(Permission.X)`."""
    sites = []
    for path in _WEB.rglob("*.ts*"):
        if "node_modules" in path.parts:
            continue
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            for match in re.finditer(r"\.global\(\s*Permission\.(\w+)", line):
                context = lines[max(0, index - _MARKER_REACH) : index + 1]
                sites.append((path, index + 1, match.group(1), context))
    return sites


def test_no_unannotated_global_check_of_a_scoped_atom():
    atoms = _client_atoms()
    violations: list[str] = []
    annotated = 0
    for path, line_no, const_name, context in _global_call_sites():
        atom = atoms.get(const_name)
        if atom is None:
            violations.append(f"{path}:{line_no} uses unknown Permission.{const_name}")
            continue
        if permission_scope_of(atom) is PermissionScope.GLOBAL:
            continue
        if any(_MARKER in ctx_line for ctx_line in context):
            annotated += 1
            continue
        violations.append(
            f"{path.relative_to(_WEB)}:{line_no} asks globally about "
            f"'{atom}' (scope: {permission_scope_of(atom).value}) — resolve against "
            f"the real scope, or annotate with '{_MARKER}: <why>' if the server "
            "genuinely checks it globally"
        )
    assert not violations, "\n".join(violations)
    # Vacuous-pass guard: the four known deliberate sites must still be seen —
    # if the scan finds none, the parser broke, not the codebase.
    assert annotated >= 4, f"expected the annotated create-a-space gates, saw {annotated}"
