"""Code-hygiene ratchets (RADD-898):
1. A broad `except Exception` that neither logs, re-raises, nor states a rationale
   is a silent swallow (the class that hid RADD-873's plugin-gating bug).
2. A string literal compared where a SAME-MODULE StrEnum member exists bypasses
   rule 2 — a renamed member silently breaks the comparison.
3. An UNDEFINED NAME (RADD-1022): a NameError on a line no test reaches.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "radd"

_LOG_METHODS = {"exception", "warning", "error", "info", "debug", "critical"}


def _handler_is_accounted_for(handler: ast.ExceptHandler, source_lines: list[str]) -> bool:
    """Logged, re-raised, or carrying a stated rationale on the except line."""
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LOG_METHODS
        ):
            return True
    # A comment on the except line is a stated rationale — reviewable, at least.
    line = source_lines[handler.lineno - 1]
    return "#" in line


def test_broad_catches_log_raise_or_explain():
    offenders = []
    for path in SRC.rglob("*.py"):
        source = path.read_text()
        lines = source.splitlines()
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or node.type is None:
                continue
            names = []
            t = node.type
            for sub in [t] if not isinstance(t, ast.Tuple) else t.elts:
                if isinstance(sub, ast.Name):
                    names.append(sub.id)
            if not ({"Exception", "BaseException"} & set(names)):
                continue
            if not _handler_is_accounted_for(node, lines):
                offenders.append(f"{path.relative_to(SRC.parent)}:{node.lineno}")
    assert not offenders, (
        "broad except with no logging, no raise, and no stated rationale:\n  "
        + "\n  ".join(sorted(offenders))
    )


def _module_enum_values(module_dir: Path) -> dict[str, str]:
    """{literal value: Enum.MEMBER} for every StrEnum defined in this module."""
    values: dict[str, str] = {}
    for path in module_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(isinstance(b, ast.Name) and b.id == "StrEnum" for b in node.bases):
                continue
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                ):
                    values[stmt.value.value] = f"{node.name}.{stmt.targets[0].id}"
    return values


#: (file-relative-to-src, lineno-agnostic literal) pairs reviewed as legitimate:
#: wire vocabularies where the enum coincidence is accidental, or values that
#: pre-date the enum on purpose. Keep SHORT — the fix is almost always the enum.
ENUM_LITERAL_ALLOWLIST: set[tuple[str, str]] = {
    # Forgejo's API pull-request `state` — a FOREIGN wire value that happens to
    # coincide with our PrStatus member; the comparison is against their JSON.
    ("radd/modules/forgejo/backfill.py", "closed"),
    # Jira's schema type strings — foreign vocabulary, same coincidence.
    ("radd/modules/jiraimport/inference.py", "user"),
}


def test_same_module_enum_values_not_compared_as_literals():
    offenders = []
    modules_dir = SRC / "modules"
    for module_dir in sorted(p for p in modules_dir.iterdir() if p.is_dir()):
        enum_values = _module_enum_values(module_dir)
        if not enum_values:
            continue
        for path in module_dir.rglob("*.py"):
            rel = str(path.relative_to(SRC.parent))
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                for comparator in node.comparators:
                    if (
                        isinstance(comparator, ast.Constant)
                        and isinstance(comparator.value, str)
                        and comparator.value in enum_values
                        and len(node.ops) == 1
                        and isinstance(node.ops[0], (ast.Eq, ast.NotEq))
                        and (rel, comparator.value) not in ENUM_LITERAL_ALLOWLIST
                    ):
                        offenders.append(
                            f"{rel}:{node.lineno}: compares literal {comparator.value!r} — "
                            f"use {enum_values[comparator.value]}"
                        )
    assert not offenders, (
        "same-module enum values compared as bare literals:\n  " + "\n  ".join(sorted(offenders))
    )


# --- 3. what ruff already knew ------------------------------------------------


def test_no_undefined_names():
    """`ruff check --select F821` over the source tree. F821 ONLY: an undefined name
    is unambiguously a defect, while F401 would flag `radd.sdk`'s re-exports and the
    register-by-import `__init__`s."""
    import shutil
    import subprocess

    root = Path(__file__).resolve().parents[1]
    ruff = shutil.which("ruff") or str(root / ".venv/bin/ruff")
    if not Path(ruff).exists():  # pragma: no cover - dev-dependency guard
        pytest.skip("ruff is not installed")

    result = subprocess.run(
        [ruff, "check", "--select", "F821", "--quiet", "src", "tests"],
        cwd=root, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "ruff found undefined names:\n" + (result.stdout or result.stderr)
    )
