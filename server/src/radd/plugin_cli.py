"""Developer tooling for trusted external plugins: python -m radd.plugin_cli --help.

Package delivery belongs to the deployment image, never an HTTP request handler.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path


class CheckError(ValueError):
    pass


def metadata(root: Path) -> tuple[dict, str]:
    data = tomllib.loads((root / "pyproject.toml").read_text())
    entries = data["project"].get("entry-points", {}).get("radd.plugins", {})
    if len(entries) != 1:
        raise CheckError("Declare exactly one [project.entry-points.\"radd.plugins\"] entry")
    module = next(iter(entries.values())).split(":")[0]
    if not re.fullmatch(r"[a-zA-Z_]\w*(\.[a-zA-Z_]\w*)*", module):
        raise CheckError("Entry point must name an importable Python module")
    return data, module


def check(root: Path, *, built: bool = False) -> dict:
    """Imports trusted source, but never calls activation hooks or opens the DB."""
    from radd.kernel import RaddPlugin
    from radd.kernel.loader import plugin_problems
    from radd.modules.pluginmgr import discovery

    data, module = metadata(root)
    source = root / "src" / module.replace(".", "/")
    if not (source / "__init__.py").is_file():
        raise CheckError(f"Expected src layout: {source / '__init__.py'}")
    sys.path.insert(0, str(root / "src"))
    importlib.invalidate_caches()
    pkg = importlib.import_module(module)
    if Path(pkg.__file__).resolve() != (source / "__init__.py").resolve():
        raise CheckError("Another package with this module name is already imported; use a fresh process")
    plugin = getattr(pkg, "plugin", None)
    if not isinstance(plugin, RaddPlugin) or plugin.core:
        raise CheckError("Export plugin = RaddPlugin(..., core=False)")
    problems = []
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", plugin.name):
        problems.append("Plugin name must use lowercase letters, numbers, hyphens or underscores")
    if not re.fullmatch(r"[a-z][a-z0-9_.-]*", plugin.id):
        problems.append("Plugin id must be a stable lowercase identifier")
    if plugin.version != data["project"]["version"]:
        problems.append("Python package version and RaddPlugin.version must match")
    known = discovery.all_known()
    problems.extend(plugin_problems(plugin, {p.name for p, _ in known.values()}))
    for other, path in known.values():
        if path != module and (other.id == plugin.id or other.name == plugin.name):
            problems.append(f"Identity collides with {path}")
    for file in source.rglob("*.py"):
        for node in ast.walk(ast.parse(file.read_text(), filename=str(file))):
            imports = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                       else [n.name for n in node.names] if isinstance(node, ast.Import) else [])
            if any(name.startswith("radd.modules.") for name in imports):
                problems.append(f"{file.relative_to(root)}: use radd.sdk instead of radd.modules internals")
    if plugin.ui and plugin.ui.remote:
        expected = f"/plugins/{plugin.name}/remoteEntry.js"
        if plugin.ui.remote != expected:
            problems.append(f"Packaged UI remote must be {expected}")
        if built and not (source / "ui/dist/remoteEntry.js").is_file():
            problems.append("UI bundle missing: build the UI before packaging")
    if problems:
        raise CheckError("\n".join(problems))
    return {"id": plugin.id, "name": plugin.name, "version": plugin.version,
            "module": module, "api_version": plugin.api_version,
            "depends_on": list(plugin.depends_on), "ui": bool(plugin.ui and plugin.ui.remote)}


def scaffold(root: Path, name: str, sdk: Path | None = None) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", name):
        raise CheckError("Use a lowercase package name such as acme-tools")
    if root.exists():
        raise CheckError(f"Destination already exists: {root}")
    if sdk is not None and not (sdk / "vite.mjs").is_file():
        raise CheckError("--sdk must point to the RADD frontend SDK directory")
    module = name.replace("-", "_")
    source = root / "src" / module
    source.mkdir(parents=True)
    (root / "pyproject.toml").write_text(f'''[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[project.entry-points."radd.plugins"]
{name} = "{module}"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{module}"]
artifacts = ["src/{module}/ui/dist/**/*"]

[tool.hatch.build.targets.wheel.exclude]
'''.replace('\n[tool.hatch.build.targets.wheel.exclude]\n', '\nexclude = ["**/node_modules/**", "**/ui/vendor/**"]\n'))
    ui_manifest = ''
    imports = 'from radd.sdk import RaddPlugin'
    if sdk:
        imports += ', PluginUiManifest, NavItemSpec'
        ui_manifest = f'''    ui=PluginUiManifest(
        nav=(NavItemSpec(key="{name}", label="{name}", path="/{name}", section="main"),),
        remote="/plugins/{name}/remoteEntry.js", ui_api_version="1.0.0",
    ),
'''
    (source / "__init__.py").write_text(f'''{imports}

plugin = RaddPlugin(
    id="{name}", name="{name}", version="0.1.0", api_version="1.0",
    core=False, description="{name} extension",
{ui_manifest})
''')
    (root / ".gitignore").write_text('.venv/\n__pycache__/\ndist/\nnode_modules/\n*.egg-info/\n')
    if sdk:
        ui = source / "ui"
        (ui / "src").mkdir(parents=True)
        shutil.copytree(sdk, ui / "vendor/plugin-sdk",
                        ignore=shutil.ignore_patterns("node_modules", "dist", ".git"))
        (ui / "package.json").write_text(json.dumps({
            "name": f"{name}-ui", "version": "0.1.0", "private": True, "type": "module",
            "scripts": {"build": "tsc --noEmit && vite build", "watch": "vite build --watch"},
            "dependencies": {"@radd/plugin-sdk": "file:vendor/plugin-sdk"},
            "devDependencies": {"@vitejs/plugin-react": "6.0.3", "vite": "8.1.5",
                                "typescript": "7.0.2", "react": "19.2.7", "react-dom": "19.2.7",
                                "@tanstack/react-query": "5.101.2", "@tanstack/react-router": "1.170.18",
                                "@types/react": "19.2.17", "@types/react-dom": "19.2.3"},
        }, indent=2) + '\n')
        (ui / "tsconfig.json").write_text(json.dumps({"compilerOptions": {
            "target": "ES2022", "lib": ["ES2022", "DOM", "DOM.Iterable"], "module": "ESNext",
            "moduleResolution": "bundler", "jsx": "react-jsx", "strict": True,
            "skipLibCheck": True, "noEmit": True}, "include": ["src"]}, indent=2))
        (ui / "vite.config.mjs").write_text('import { raddRemote } from "@radd/plugin-sdk/vite";\n'
            'import { fileURLToPath } from "node:url";\n'
            'export default raddRemote(fileURLToPath(new URL(".", import.meta.url)));\n')
        (ui / "src/index.tsx").write_text(f'''import {{ definePlugin, SlotId }} from "@radd/plugin-sdk";

export default definePlugin({{
  contributions: [{{ slot: SlotId.routePage, match: "/{name}",
    render: () => <section><h1>{name}</h1><p>Your plugin is running.</p></section> }}],
}});
''')
    (root / "README.md").write_text(f'''# {name}

Independent, trusted RADD plugin. Backend: `src/{module}/__init__.py`.

From the RADD server environment:

```sh
python -m radd.plugin_cli check {root}
python -m radd.plugin_cli develop {root}
python -m radd.plugin_cli build {root}
```

Enable in Settings → Plugins, then restart the web and worker processes.
Python edits require restart; UI edits can use `npm run watch` in
`src/{module}/ui` followed by a browser refresh. For the first UI build, run
`npm install` there and commit package-lock.json; subsequent builds use npm ci.
The vendored frontend SDK snapshot can be committed in this repository.
Backend code imports radd.sdk; frontend code imports @radd/plugin-sdk.

Build emits a wheel, SHA-256 manifest, and a Containerfile in dist/.
Use a pinned RADD base image, build one image for web and worker, and deploy it.
Activation does not install Python dependencies or run schema migrations.
Declarative entities support initial table creation; schema upgrades need an
explicit reviewed deployment migration. Disabling and forgetting keep data.
''')


def build(root: Path, toolchain: Path | None = None) -> dict:
    info = check(root)
    if info['ui']:
        ui = root / "src" / info['module'].replace('.', '/') / 'ui'
        if toolchain:
            # An explicit local toolchain supports development without npm and
            # is never bundled. Normal independent repositories use npm ci.
            subprocess.run(['node', str(toolchain / 'typescript/bin/tsc'), '--noEmit'], cwd=ui, check=True)
            subprocess.run(['node', str(toolchain / 'vite/bin/vite.js'), 'build'], cwd=ui, check=True)
        else:
            if not (ui / 'package-lock.json').is_file():
                raise CheckError(f"Run npm install in {ui} once and commit package-lock.json")
            subprocess.run(['npm', 'ci'], cwd=ui, check=True)
            subprocess.run(['npm', 'run', 'build'], cwd=ui, check=True)
    check(root, built=True)
    # A fresh output directory prevents accidentally shipping stale wheels.
    out = root / 'dist'
    out.mkdir(exist_ok=True)
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        subprocess.run(['uv', 'build', '--wheel', '--out-dir', temp, str(root)], check=True)
        wheel = next(Path(temp).glob('*.whl'))
        with zipfile.ZipFile(wheel) as archive:
            if info['ui'] and f"{info['module'].replace('.', '/')}/ui/dist/remoteEntry.js" not in archive.namelist():
                raise CheckError("Wheel omitted the UI bundle; check Hatch artifacts configuration")
        target = out / wheel.name
        shutil.copyfile(wheel, target)
    info['wheel'] = target.name
    info['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    (out / 'plugin.json').write_text(json.dumps(info, indent=2) + '\n')
    (out / 'Containerfile').write_text(f'''# Build with: podman build --build-arg RADD_IMAGE=ghcr.io/radd-hq/radd:<version> -f dist/Containerfile dist
ARG RADD_IMAGE
FROM ${{RADD_IMAGE}}
USER root
COPY {target.name} /tmp/{target.name}
RUN echo "{info['sha256']}  /tmp/{target.name}" | sha256sum -c - \\
 && uv pip install --python /opt/venv/bin/python --no-deps /tmp/{target.name} \\
 && uv pip check --python /opt/venv/bin/python \\
 && rm /tmp/{target.name}
USER radd
''')
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    new = commands.add_parser('new', help='Create an independent plugin repository')
    new.add_argument('path', type=Path)
    new.add_argument('--name', required=True)
    new.add_argument('--sdk', type=Path, help='Include UI using a vendored copy of this frontend SDK')
    for command in ('check', 'build', 'develop'):
        sub = commands.add_parser(command)
        sub.add_argument('path', type=Path)
        if command == 'build':
            sub.add_argument('--toolchain', type=Path, help='Explicit existing node_modules for local builds')
    args = parser.parse_args(argv)
    try:
        root = args.path.resolve()
        if args.command == 'new':
            scaffold(root, args.name, args.sdk.resolve() if args.sdk else None)
            print(f'Created {root}. Next: python -m radd.plugin_cli check {root}')
        elif args.command == 'check':
            print(json.dumps(check(root), indent=2))
        elif args.command == 'build':
            print(json.dumps(build(root, args.toolchain.resolve() if args.toolchain else None), indent=2))
        else:
            check(root)
            subprocess.run(['uv', 'pip', 'install', '--python', sys.executable, '--no-deps', '-e', str(root)], check=True)
            subprocess.run(['uv', 'pip', 'check', '--python', sys.executable], check=True)
            print('Package linked. Install and enable in Settings → Plugins; restart web and workers.')
    except (CheckError, OSError, ValueError, KeyError, ImportError, subprocess.CalledProcessError) as exc:
        print(f'Plugin workflow failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
