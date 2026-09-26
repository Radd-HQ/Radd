"""RADD-810 — the client-gate scope audit, as a test. A `perms.global(X)` in the SPA
(host or plugin UI) where X is not a GLOBAL-scope atom fails for the holder of X at
its real scope, so the control silently vanishes for exactly the people it was
built for. Deliberately global sites carry a `deliberately-global` marker. A new
unannotated mismatch fails with file:line, and a marker without a mismatch is
flagged too (a stale marker invites copying).
"""

import re
from pathlib import Path

from radd.modules.auth.types import PermissionScope, permission_scope_of

_WEB = Path(__file__).resolve().parents[2] / "web" / "src"
_TYPES = _WEB / "lib" / "types" / "permissions.ts"
#: Plugin UI packages ship their own atom constants (RADD-1392: the wiki's
#: `PagePermission`), so their call sites are audited too.
_MODULES = Path(__file__).resolve().parents[1] / "src" / "radd" / "modules"

_MARKER = "deliberately-global"
#: How many lines above a call site the marker comment may sit (JSX block
#: comments span a few lines).
_MARKER_REACH = 8


def _sources() -> list[Path]:
    roots = [_WEB, *(ui for ui in _MODULES.glob("*/ui/src"))]
    return [path for root in roots for path in root.rglob("*.ts*") if "node_modules" not in path.parts]


def _client_atoms() -> dict[str, str]:
    """Every atom constant: {"Permission.name": atom, "PagePermission.name": atom, …}."""
    body = _TYPES.read_text()
    block = re.search(r"export const Permission = \{(.*?)\n\} as const;", body, re.S)
    assert block, f"could not find the Permission const in {_TYPES}"
    atoms = {f"Permission.{name}": atom for name, atom in re.findall(r'(\w+):\s*"([^"]+)"', block.group(1))}
    for path in _sources():
        for const, inner in re.findall(r"export const (\w+Permission) = \{(.*?)\} as const;", path.read_text(), re.S):
            atoms |= {f"{const}.{name}": atom for name, atom in re.findall(r'(\w+):\s*"([^"]+)"', inner)}
    return atoms


def _global_call_sites() -> list[tuple[Path, int, str, list[str]]]:
    """(file, line-no, const-name, preceding-lines) for every `.global(<X>Permission.name)`."""
    sites = []
    for path in _sources():
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            for match in re.finditer(r"\.global\(\s*(\w*Permission\.\w+)", line):
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
            violations.append(f"{path}:{line_no} uses unknown {const_name}")
            continue
        if permission_scope_of(atom) is PermissionScope.GLOBAL:
            continue
        if any(_MARKER in ctx_line for ctx_line in context):
            annotated += 1
            continue
        violations.append(
            f"{path.name}:{line_no} asks globally about "
            f"'{atom}' (scope: {permission_scope_of(atom).value}) — resolve against "
            f"the real scope, or annotate with '{_MARKER}: <why>' if the server "
            "genuinely checks it globally"
        )
    assert not violations, "\n".join(violations)
    # Creation/template/reindex in Pages settings intentionally retain one
    # global gate; navigation and per-space actions no longer use it.
    assert annotated >= 1, f"expected the annotated instance-space gate, saw {annotated}"
