#!/usr/bin/env python3
"""Refresh the source inventory without treating discovery as an ownership review.

Reads Python manifests through AST (no application/database boot). Records all backend,
host and SDK sources and source-level imports. Review decisions live in review.json and
are retained only for unchanged files; changed files must be reviewed again.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research/plugin-isolation"
MODULES = ROOT / "server/src/radd/modules"


def value(node: ast.AST):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return ast.unparse(node)


def inventory():
    modules = {}
    for manifest in sorted(MODULES.glob("*/__init__.py")):
        tree = ast.parse(manifest.read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id in {"RaddPlugin", "Module"}]
        if not calls:
            continue
        fields = {k.arg: value(k.value) for k in calls[0].keywords if k.arg}
        modules[manifest.parent.name] = {
            "manifest": str(manifest.relative_to(ROOT)),
            "declarations": fields,
            "ui_sources": sorted(str(p.relative_to(ROOT)) for p in (manifest.parent / "ui/src").rglob("*") if p.is_file()),
        }
    files = {}
    for base in (ROOT / "server/src/radd", ROOT / "web/src", ROOT / "web/packages/plugin-sdk/src", ROOT / "examples"):
        for path in sorted(base.rglob("*")):
            if path.suffix not in {".py", ".ts", ".tsx", ".css"} or any(x in path.parts for x in ("node_modules", "dist", "__pycache__")):
                continue
            rel = str(path.relative_to(ROOT))
            source = path.read_text()
            imports = []
            if path.suffix == ".py":
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, ast.ImportFrom):
                        imports.append({"line": node.lineno, "module": "." * node.level + (node.module or ""), "names": [n.name for n in node.names]})
                    elif isinstance(node, ast.Import):
                        imports.extend({"line": node.lineno, "module": n.name} for n in node.names)
            else:
                # Discovery hints only; semantic boundary tests are a separate verification gate.
                pattern = r'''(?:\bfrom\s*|\bimport\s*\(?\s*)["']([^"']+)["']'''
                imports = [{"line": source.count("\n", 0, m.start()) + 1, "module": m.group(1)} for m in re.finditer(pattern, source)]
            module = path.relative_to(MODULES).parts[0] if path.is_relative_to(MODULES) else None
            files[rel] = {"sha256": hashlib.sha256(source.encode()).hexdigest(), "module_directory": module,
                          "imports": imports}
    return {"modules": modules, "files": files}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = inventory()
    review_path = OUT / "review.json"
    previous = json.loads(review_path.read_text()) if review_path.exists() else {}
    review = {}
    for path, entry in data["files"].items():
        old = previous.get(path, {})
        review[path] = old if old.get("sha256") == entry["sha256"] else {
            "sha256": entry["sha256"], "status": "unreviewed", "owner": None,
            "evidence": [], "issue": None,
        }
    (OUT / "inventory.json").write_text(json.dumps(data, indent=2) + "\n")
    review_path.write_text(json.dumps(review, indent=2) + "\n")
    print(f'{len(data["modules"])} module manifests; {len(data["files"])} source files; '
          f'{sum(r["status"] == "unreviewed" for r in review.values())} files await ownership review')


if __name__ == "__main__":
    main()
