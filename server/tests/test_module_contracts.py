"""The architecture ratchet (RADD-885) — CLAUDE.md rule 1, enforced.

Two assertions over the real import graph (AST-walked, deferred imports
included), so a violation fails the suite instead of surfacing in an audit
years later:

1. **Models are module-private beyond the spine.** The de-facto spine the
   2026-08 audit measured is wider than the written one: `WorkItem` (14 FK
   dependents), `workflow.State` (every item query joins it) and `Team` (8
   dependents) join `User`/`Project` as READ-ONLY blessings — reads may join
   them; writes still go through the owner's service. Everything else's
   `models.py` is off-limits, with the audit's remaining findings frozen in
   `MODEL_IMPORT_ALLOWLIST` — a burn-down list (RADD-886..892). Fixing a seam
   removes its entry; ADDING one needs a reason reviewed here.

2. **Imports are declared.** Every `radd.modules.X` import in module Y appears
   in Y's `depends_on` (load-ordering) or `weak_depends` (declared, not
   ordered: deferred reverse reaches + feature-detected seams). No allowlist —
   this one holds outright.
"""

import ast
from pathlib import Path

from radd.config import settings
from radd.kernel import registries

MODULES_DIR = Path(__file__).resolve().parents[1] / "src" / "radd" / "modules"
KERNEL_DIR = MODULES_DIR.parent / "kernel"

#: Rule-1 spine: models importable by everyone. items/workflow/teams/fields are
#: READ-ONLY blessings (the audit's §3b/§3d reality — WorkItem has 14 FK
#: dependents, every item query joins State, and FieldDefinition is the
#: custom-field vocabulary every list surface renders); auth carries User (the
#: original exception) and projects Project. Writes still go through the
#: owner's service, always.
SPINE = {"auth", "projects", "items", "workflow", "teams", "fields"}

#: (importing module, imported module) pairs the audit found reaching a
#: non-spine models.py — frozen so the class cannot GROW. Shrunk by the
#: RADD-887/888 seam work and EMPTIED by RADD-892, which inverted auth's reach
#: into `pages.models` into a registered GrantScopeSpec. An addition needs a
#: reason reviewed here; the burn-down is finished.
MODEL_IMPORT_ALLOWLIST: set[tuple[str, str]] = set()


def _module_edges(module: str) -> list[tuple[str, str | None, str]]:
    """(imported module, first submodule or None, file:line) for every
    `radd.modules.X` import under this module's directory."""
    edges = []
    for path in (MODULES_DIR / module).rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        where = f"{path.relative_to(MODULES_DIR.parent)}"
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if parts[:2] == ["radd", "modules"] and len(parts) >= 3:
                    target, sub = parts[2], parts[3] if len(parts) > 3 else None
                    # `from radd.modules.x import models` counts as a models import
                    if sub is None and any(a.name == "models" for a in node.names):
                        sub = "models"
                    edges.append((target, sub, f"{where}:{node.lineno}"))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if parts[:2] == ["radd", "modules"] and len(parts) >= 3:
                        edges.append(
                            (parts[2], parts[3] if len(parts) > 3 else None, f"{where}:{node.lineno}")
                        )
    return edges


def _kernel_module_imports() -> list[str]:
    """Every `radd.modules.*` import anywhere under `kernel/`, deferred included."""
    found = []
    for path in KERNEL_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                if name.split(".")[:2] == ["radd", "modules"]:
                    found.append(f"{path.relative_to(KERNEL_DIR.parent)}:{node.lineno}: {name}")
    return found


def _all_modules() -> list[str]:
    return sorted(
        p.name for p in MODULES_DIR.iterdir() if p.is_dir() and (p / "__init__.py").exists()
    )


def test_models_stay_behind_the_spine():
    violations = []
    for module in _all_modules():
        for target, sub, where in _module_edges(module):
            if sub != "models" or target == module or target in SPINE:
                continue
            if (module, target) in MODEL_IMPORT_ALLOWLIST:
                continue
            violations.append(f"{where}: {module} imports {target}.models")
    assert not violations, (
        "non-spine models imports outside the burn-down allowlist:\n  "
        + "\n  ".join(sorted(violations))
    )


def test_allowlist_only_shrinks():
    """An allowlist entry whose import no longer exists is stale — delete it,
    so the ratchet actually ratchets."""
    live = set()
    for module in _all_modules():
        for target, sub, _ in _module_edges(module):
            if sub == "models" and target != module:
                live.add((module, target))
    stale = MODEL_IMPORT_ALLOWLIST - live
    assert not stale, f"allowlist entries with no surviving import: {sorted(stale)}"


def test_the_kernel_imports_no_plugin():
    """The kernel is mechanism; a plugin is policy. Nothing under `kernel/` may
    import `radd.modules.*` — including from inside a handler, which is how
    `kernel/entities.py` reached auth/projects/events for years while its own
    docstring claimed purity (RADD-892). Policies arrive through
    `kernel.hosts.EntityHost` and the contribution registries."""
    found = _kernel_module_imports()
    assert not found, "the kernel imports plugins:\n  " + "\n  ".join(found)


def test_every_import_is_declared():
    import importlib

    declared: dict[str, set[str]] = {}
    for module in _all_modules():
        plugin = getattr(importlib.import_module(f"radd.modules.{module}"), "plugin", None)
        if plugin is None:
            continue
        declared[module] = set(plugin.depends_on) | set(getattr(plugin, "weak_depends", ()))

    missing = []
    for module, deps in declared.items():
        imported = {target for target, _, _ in _module_edges(module) if target != module}
        for target in sorted(imported - deps):
            missing.append(f"{module} imports {target} but declares no dependency on it")
    assert not missing, "undeclared module dependencies:\n  " + "\n  ".join(missing)


def test_weak_depends_name_real_modules():
    import importlib

    known = set(_all_modules())
    bad = []
    for module in _all_modules():
        plugin = getattr(importlib.import_module(f"radd.modules.{module}"), "plugin", None)
        if plugin is None:
            continue
        for name in getattr(plugin, "weak_depends", ()):  # typos declare nothing
            if name not in known:
                bad.append(f"{module}.weak_depends names unknown module {name!r}")
    assert not bad, "\n".join(bad)
