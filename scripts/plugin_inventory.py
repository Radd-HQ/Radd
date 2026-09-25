#!/usr/bin/env python3
"""Inventory repository artifacts without mistaking discovery for ownership review.

Git defines tracked scope, including unknown file types. New implementation/config files
are included before staging. Untracked documents/assets and gitignored local state stay
outside discovery. Import/declaration extraction is evidence to inspect, not an approval.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
LEDGER = "research/plugin-isolation"
GENERATED = {f"{LEDGER}/{name}.json" for name in ("inventory", "review", "retired")}
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".sh", ".sql"}
CONFIG_SUFFIXES = {".json", ".toml", ".yaml", ".yml", ".ini", ".lock", ".tpl", ".mako", ".html"}
NEW_ROOTS = {"server", "web", "sdk", "examples", "scripts", "deploy", ".github"}
STATUSES = {"unreviewed", "partially_reviewed", "reviewed", "exception"}


def git_paths(root: Path, *args: str) -> set[str]:
    output = subprocess.check_output(["git", "ls-files", "-z", *args], cwd=root)
    return {name.decode() for name in output.split(b"\0") if name}


def candidates(root: Path) -> list[str]:
    tracked = git_paths(root, "--cached")
    new = git_paths(root, "--others", "--exclude-standard")
    # Tracked files never pass through an extension allowlist. Unknown tracked
    # artifacts are explicitly unclassified, not silently dropped.
    new = {p for p in new if Path(p).parts[0] in NEW_ROOTS and (
        Path(p).suffix in SOURCE_SUFFIXES | CONFIG_SUFFIXES
        or "Containerfile" in Path(p).name or "Dockerfile" in Path(p).name
    )}
    return sorted((tracked | new) - GENERATED)


def role(path: str) -> str:
    p = Path(path)
    if path.startswith("web/public/shared/"):
        return "generated_source"
    if "migrations" in p.parts:
        return "migration"
    if "sample_data" in p.parts or "fixtures" in p.parts or "baseline" in p.name:
        return "fixture_or_baseline"
    if "tests" in p.parts or ".test." in p.name or p.name.startswith("test_"):
        return "test"
    if p.suffix in {".md", ".rst"} or p.name in {"LICENSE", "CODEOWNERS", "OFL.txt"}:
        return "documentation"
    if p.suffix in SOURCE_SUFFIXES:
        return "tooling_source" if "scripts" in p.parts and "/modules/" not in path else "runtime_source"
    if p.suffix in CONFIG_SUFFIXES | {".version"} or any(name in p.name for name in ("Containerfile", "Dockerfile", "Caddyfile")) or p.name.startswith("."):
        return "configuration"
    if p.suffix in {".png", ".svg", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2"}:
        return "asset"
    return "unclassified"


def ast_value(node: ast.AST):
    try:
        # Canonical JSON types keep refresh/check equal across tuple literals.
        return json.loads(json.dumps(ast.literal_eval(node)))
    except (ValueError, TypeError):
        return ast.unparse(node)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def discover(root: Path) -> dict:
    files, modules, packages, errors = {}, {}, {}, []
    for rel in candidates(root):
        path = root / rel
        if not path.exists() and not path.is_symlink():
            continue  # Retired entries below account for deletions, including unstaged ones.
        if path.is_symlink():
            # Do not follow tracked symlinks outside the repository or into ignored data.
            import os
            raw = os.readlink(path).encode()
        elif path.is_file():
            raw = path.read_bytes()
        else:
            errors.append(f"{rel}: unsupported tracked directory/submodule")
            continue
        parts = Path(rel).parts
        module = parts[4] if parts[:4] == ("server", "src", "radd", "modules") and len(parts) > 4 else None
        entry = {"sha256": hashlib.sha256(raw).hexdigest(), "module_directory": module,
                 "role": "symlink" if path.is_symlink() else role(rel), "imports": []}
        files[rel] = entry
        if path.is_symlink():
            entry["target"] = raw.decode()
            continue
        try:
            if path.suffix == ".py":
                tree = ast.parse(raw, filename=rel)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        entry["imports"].append({"line": node.lineno, "module": "." * node.level + (node.module or ""), "names": [n.name for n in node.names]})
                    elif isinstance(node, ast.Import):
                        entry["imports"].extend({"line": node.lineno, "module": n.name} for n in node.names)
                if (module and rel == f"server/src/radd/modules/{module}/__init__.py") or rel.startswith("examples/"):
                    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                             and isinstance(n.func, ast.Name) and n.func.id in {"RaddPlugin", "Module"}]
                    for index, call in enumerate(calls):
                        key = (module if index == 0 else f"{module}:{index}") if module else f"example:{rel}:{index}"
                        fields = {k.arg: ast_value(k.value) for k in call.keywords if k.arg}
                        ui_prefix = str(path.parent.relative_to(root)) + "/ui/src/"
                        # Matches register_plugin_ui_dir: UI is colocated with
                        # the Python module for builtins and external packages.
                        modules[key] = {"manifest": rel, "declarations": fields, "ui_prefix": ui_prefix}
            elif path.suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
                source = raw.decode()
                pattern = r'''(?:\bfrom\s*|\b(?:import|require)\s*\(?\s*)["']([^"']+)["']'''
                entry["imports"] = [{"line": source.count("\n", 0, m.start()) + 1, "module": m.group(1)} for m in re.finditer(pattern, source)]
            if path.name == "package.json":
                package = json.loads(raw)
                keys = ("name", "version", "type", "dependencies", "devDependencies", "peerDependencies", "peerDependenciesMeta", "optionalDependencies", "workspaces", "scripts")
                packages[rel] = {key: package[key] for key in keys if key in package}
            elif path.name == "pyproject.toml":
                package = tomllib.loads(raw.decode())
                packages[rel] = {key: package[key] for key in ("project", "build-system") if key in package}
        except (SyntaxError, UnicodeError, ValueError) as exc:
            # A failed parse remains visible and makes the check fail. Never
            # silently remove a file because the discovery parser cannot read it.
            message = f"{type(exc).__name__}: {exc}"
            entry["discovery_error"] = message
            errors.append(f"{rel}: {message}")
    for item in modules.values():
        prefix = item.pop("ui_prefix")
        item["ui_sources"] = [p for p in files if p.startswith(prefix)]
    return {"scope": {
        "tracked": "Every existing tracked artifact, regardless of extension; symlinks are recorded without following them.",
        "new_files": "Nonignored implementation/configuration files in server, web, sdk, examples, scripts, deploy and .github; stage other new artifacts to include them.",
        "excluded": {p: "Generated audit ledger; excluded to avoid self-referential hashes." for p in sorted(GENERATED)},
        "limitations": "Static declarations and import hints do not establish semantic ownership, runtime reachability, or completeness of dynamically constructed registrations.",
    }, "modules": modules, "packages": packages, "files": files, "discovery_errors": errors}


def refreshed(root: Path, data: dict) -> tuple[dict, dict]:
    previous = read_json(root / LEDGER / "review.json")
    old_files = read_json(root / LEDGER / "inventory.json").get("files", {})
    retired = read_json(root / LEDGER / "retired.json")
    review = {}
    for path, entry in data["files"].items():
        old = previous.get(path, {})
        review[path] = old if old.get("sha256") == entry["sha256"] else {
            "sha256": entry["sha256"], "status": "unreviewed", "owner": None,
            "evidence": [], "issue": None,
        }
        retired.pop(path, None)
    for path in sorted(set(old_files) - set(data["files"])):
        retired[path] = {"last_sha256": old_files[path]["sha256"],
                         "previous_review": previous.get(path), "status": "unreviewed",
                         "owner": None, "issue": None, "evidence": []}
    return review, dict(sorted(retired.items()))


def review_errors(review: dict, *, require_reviewed: bool) -> list[str]:
    errors = []
    for path, entry in review.items():
        status = entry.get("status")
        if status not in STATUSES:
            errors.append(f"{path}: invalid review status {status!r}")
        if status in {"reviewed", "partially_reviewed", "exception"}:
            if not all(isinstance(entry.get(key), str) and entry[key].strip() for key in ("owner", "issue")) or not entry.get("evidence"):
                errors.append(f"{path}: ownership review requires owner, issue and evidence")
            if not isinstance(entry.get("evidence"), list) or not all(isinstance(e, str) and e.strip() for e in entry.get("evidence", [])):
                errors.append(f"{path}: evidence must be a list of nonempty references or findings")
        if status == "exception" and not entry.get("reason"):
            errors.append(f"{path}: exception requires a concrete reason")
        if require_reviewed and status not in {"reviewed", "exception"}:
            errors.append(f"{path}: ownership remains {status}")
    return errors


def run(root: Path, *, check: bool = False, require_reviewed: bool = False) -> list[str]:
    data = discover(root)
    review, retired = refreshed(root, data)
    output = {"inventory": data, "review": review, "retired": retired}
    errors = list(data["discovery_errors"])
    errors += review_errors(review, require_reviewed=require_reviewed)
    errors += review_errors(retired, require_reviewed=require_reviewed)
    directory = root / LEDGER
    if check:
        for name, expected in output.items():
            path = directory / f"{name}.json"
            if not path.exists() or read_json(path) != expected:
                errors.append(f"{name}.json is stale; run python scripts/plugin_inventory.py and review changed entries")
    else:
        directory.mkdir(parents=True, exist_ok=True)
        for name, value in output.items():
            (directory / f"{name}.json").write_text(json.dumps(value, indent=2) + "\n")
    counts = {status: sum(e["status"] == status for e in review.values()) for status in sorted(STATUSES)}
    print(f'{len(data["modules"])} discovered manifests; {len(data["files"])} artifacts; '
          f'{len(retired)} retired entries; review: {json.dumps(counts, sort_keys=True)}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate freshness without changing the ledger")
    parser.add_argument("--require-reviewed", action="store_true", help="Also require evidence-backed ownership/exception for every current and retired entry")
    args = parser.parse_args()
    errors = run(ROOT, check=args.check or args.require_reviewed, require_reviewed=args.require_reviewed)
    for message in errors[:30]:
        print(message)
    if len(errors) > 30:
        print(f"…and {len(errors) - 30} further errors")
    raise SystemExit(bool(errors))


if __name__ == "__main__":
    main()
