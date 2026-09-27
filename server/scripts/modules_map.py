"""Generate docs/modules.md: structure from the plugin manifests, prose from docs/modules-notes.md.

Every structural fact in the map (core or optional, bundled or remote UI, depends_on,
weak_depends, event types, permission atoms, settings keys, nav items, and each kind of
contribution) is read from the `RaddPlugin` manifests and the plugins' `ui/package.json`, so
none of it is hand-maintained. The only hand-written text is docs/modules-notes.md: one
paragraph per module plus a few cross-cutting sections, each under a length cap.
`tests/test_modules_map.py` fails when the checked-in map differs from this output.

    uv --directory server run python scripts/modules_map.py
"""

import ast
import importlib
import json
import re
from dataclasses import dataclass, fields
from pathlib import Path

from radd.config import Settings
from radd.kernel import RaddPlugin
from radd.kernel.sockets import Socket

REPO = Path(__file__).resolve().parents[2]
MAP = REPO / "docs" / "modules.md"
NOTES = REPO / "docs" / "modules-notes.md"
SOURCE = REPO / "server" / "src" / "radd"
REGENERATE = "uv --directory server run python scripts/modules_map.py"

MODULE_CAP = 750  # characters in one module's paragraph
SECTION_CAP = 2500  # characters in one cross-cutting section
ISSUE_KEY = re.compile(r"\bRADD-\d+")
LIST_MARKS = ("- ", "* ", "| ", "#", "1. ")

# Manifest fields that are wiring, not contributions a reader navigates by.
NOT_RENDERED = {
    "routers", "exception_handlers", "openapi_augmentors", "on_startup", "on_shutdown",
    "consumer_descriptions", "consumer_resume", "depends_on", "weak_depends",
    "event_types", "permissions", "settings_keys",
}


def _name(spec: object) -> str:
    if isinstance(spec, str):
        return spec
    for attr in ("key", "name", "event_type", "entity_type", "resource_type", "root"):
        value = getattr(spec, attr, None)
        if isinstance(value, str) and value:
            return value
    raise ValueError(f"modules_map: no display key on {spec!r}")


# (manifest field, group, label, how one entry reads). The groups become the bullets.
CONTRIBUTIONS: tuple[tuple[str, str, str, object], ...] = (
    ("crud_resources", "Access", "CRUD resources", lambda s: f"{s.key} ({s.scope}, {s.manage})"),
    ("relations", "Access", "relations", lambda s: f"{s.resource}@{s.key}"),
    ("relation_domains", "Access", "relation domains", lambda pair: f"{pair[0]} → {pair[1]}"),
    ("row_guards", "Access", "row guards", lambda s: s.resource),
    ("access_resources", "Access", "access resources", lambda s: s.resource_type),
    ("grant_scopes", "Access", "grant scopes", _name),
    ("project_relations", "Access", "project relations", _name),
    ("mcp_tools", "Contributes", "MCP tools", _name),
    ("automation_nodes", "Contributes", "automation nodes", _name),
    ("trigger_kinds", "Contributes", "trigger kinds", _name),
    ("token_providers", "Contributes", "template tokens", lambda s: "{{" + s.root + ".*}}"),
    ("automation_templates", "Contributes", "automation templates", _name),
    ("notification_kinds", "Contributes", "notification kinds", _name),
    ("integrations", "Contributes", "socket providers", lambda s: f"{s.socket}: {s.name}"),
    ("searchables", "Contributes", "searchables", _name),
    ("slq_fields", "Contributes", "SLQ fields", _name),
    ("view_types", "Contributes", "view types", _name),
    ("widget_types", "Contributes", "widget types", _name),
    ("page_extensions", "Contributes", "page extensions", lambda s: f"radd:{s.name}"),
    ("capabilities", "Contributes", "capabilities", _name),
    ("nav_facts", "Contributes", "nav facts", _name),
    ("consumer_names", "Runs", "event consumers", _name),
    ("tasks", "Runs", "periodic tasks", _name),
    ("entities", "Data", "declared entities (kernel auto-wires table, CRUD, events, atoms)",
     lambda s: f"{s.key} ({s.table})"),
    ("entity_refs", "Data", "entity refs", _name),
    ("entity_links", "Data", "audit links", _name),
    ("record_local_entities", "Data", "record-local entities", _name),
    ("project_purges", "Data", "project purges", _name),
    ("cascades", "Data", "cascades", _name),
)
GROUPS = ("Access", "Contributes", "Runs", "Data")


@dataclass(frozen=True)
class Module:
    name: str
    plugin: RaddPlugin
    order: int  # 1-based load position in `modules`; 0 = installable, not bootstrapped
    ui: str


@dataclass(frozen=True)
class Notes:
    preamble: dict[str, str]
    modules: dict[str, str]
    sections: dict[str, str]


def _ui_kind(package: Path, plugin: RaddPlugin) -> str:
    """bundled | remote | host (core, screens in web/src) | none, `+ contracts` for a types-only package."""
    manifest = package / "ui" / "package.json"
    if manifest.exists() and json.loads(manifest.read_text()).get("radd", {}).get("bundled"):
        return "bundled"
    if plugin.ui is not None and plugin.ui.remote:
        return "remote"
    kind = "host" if plugin.core else "none"
    return f"{kind} + contracts" if manifest.exists() else kind


def load_modules() -> list[Module]:
    """Every in-repo plugin, in load order. Defaults, not the environment: `RADD_MODULES`
    may reorder or drop plugins on one machine; the map describes the shipped set."""
    boot = Settings.model_fields["modules"].default
    installable = Settings.model_fields["installable_plugins"].default
    out = []
    for order, path in [*enumerate(boot, 1), *((0, p) for p in installable)]:
        package = importlib.import_module(path)
        plugin = package.plugin
        folder = Path(package.__file__).parent
        out.append(Module(folder.name, plugin, order, _ui_kind(folder, plugin)))
    return out


def unrendered_fields() -> set[str]:
    """Manifest fields neither rendered nor skipped: a new contribution kind needs a label first."""
    known = NOT_RENDERED | {field for field, *_ in CONTRIBUTIONS}
    other = {"name", "description", "id", "version", "api_version", "core", "enabled_by_default", "ui"}
    return {f.name for f in fields(RaddPlugin)} - known - other


def socket_readers() -> dict[str, list[str]]:
    """Socket → the modules that READ it: every `Socket.X` outside an `IntegrationSpec(...)`."""
    members = {s.name: s.value for s in Socket}
    readers: dict[str, set[str]] = {s.value: set() for s in Socket}
    for file in sorted(SOURCE.rglob("*.py")):
        if file.name == "sockets.py" and file.parent.name == "kernel":
            continue
        tree = ast.parse(file.read_text())
        provided = {
            id(call.args[0])
            for call in ast.walk(tree)
            if isinstance(call, ast.Call) and call.args
            and getattr(call.func, "id", getattr(call.func, "attr", "")) == "IntegrationSpec"
        }
        parts = file.relative_to(SOURCE).parts
        owner = parts[1] if parts[0] == "modules" else parts[0].removesuffix(".py")
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr in members and id(node) not in provided
                    and getattr(node.value, "id", getattr(node.value, "attr", "")) == "Socket"):
                readers[members[node.attr]].add(owner)
    return {socket: sorted(names) for socket, names in readers.items()}


def parse_notes(text: str) -> Notes:
    """`## Preamble` / `## Modules` / `## Sections`, each holding `### <title>` entries."""
    parts: dict[str, dict[str, list[str]]] = {"Preamble": {}, "Modules": {}, "Sections": {}}
    part, entry, fenced = None, None, False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            part, entry = line[3:].strip(), None
            if part not in parts:
                raise ValueError(f"modules-notes.md: unknown part {part!r}")
            continue
        if not fenced and line.startswith("### "):
            if part is None:
                raise ValueError(f"modules-notes.md: {line!r} is outside a part")
            entry = line[4:].strip()
            if entry in parts[part]:
                raise ValueError(f"modules-notes.md: {entry!r} appears twice")
            parts[part][entry] = []
            continue
        if part and entry:
            parts[part][entry].append(line)
    body = {p: {k: "\n".join(v).strip() for k, v in entries.items()} for p, entries in parts.items()}
    return Notes(body["Preamble"], body["Modules"], body["Sections"])


def problems(modules: list[Module], notes: Notes) -> list[str]:
    """Everything that keeps the map honest and short; empty when it may be generated."""
    out = [f"RaddPlugin field {f!r} has no label in modules_map.CONTRIBUTIONS" for f in sorted(unrendered_fields())]
    names = [m.name for m in modules]
    out += [f"module {n!r} has no paragraph in modules-notes.md" for n in names if n not in notes.modules]
    out += [f"modules-notes.md describes {n!r}, which is not a plugin" for n in notes.modules if n not in names]
    for name, text in notes.modules.items():
        if len(text) > MODULE_CAP:
            out.append(f"{name}: paragraph is {len(text)} characters (cap {MODULE_CAP})")
        if "\n\n" in text or any(line.startswith(LIST_MARKS) for line in text.splitlines()):
            out.append(f"{name}: write one paragraph (no blank lines, lists or tables)")
    for title, text in {**notes.preamble, **notes.sections}.items():
        if len(text) > SECTION_CAP:
            out.append(f"section {title!r} is {len(text)} characters (cap {SECTION_CAP})")
    for title, text in {**notes.preamble, **notes.modules, **notes.sections}.items():
        if ISSUE_KEY.search(text):
            out.append(f"{title}: issue keys belong in the tracker, not the map")
    return out


def _code(values: object) -> str:
    return ", ".join(f"`{v}`" for v in values) or "—"


def _kind(module: Module) -> str:
    if module.order == 0:
        return "optional, installable" + ("" if module.plugin.enabled_by_default else " (off by default)")
    return "core" if module.plugin.core else "optional"


def _module_block(module: Module, paragraph: str) -> list[str]:
    plugin = module.plugin
    facts = [f"**{_kind(module)}**", f"UI: {module.ui}"]
    facts.append(f"load order {module.order}" if module.order else "loaded when installed")
    if plugin.id != module.name:
        facts.append(f"plugin id `{plugin.id}`")
    heads = set(plugin.head_consumers())
    lines = [f"### {module.name}", "", " · ".join(facts), "", plugin.description.strip(), "", paragraph, ""]
    if plugin.event_types:
        lines.append(f"- **Events:** {_code(e.event_type for e in plugin.event_types)}")
    if plugin.permissions:
        atoms = (f"{p.key} ({p.scope})" for p in plugin.permissions)
        lines.append(f"- **Permissions:** {_code(atoms)}")
    if plugin.settings_keys:
        keys = (f"{s.key} ({'/'.join(s.scopes)})" for s in plugin.settings_keys)
        lines.append(f"- **Settings:** {_code(keys)}")
    if plugin.ui is not None and plugin.ui.nav:
        nav = (f"{n.label} → {n.path} ({n.section}{'/' + n.group if n.group else ''})" for n in plugin.ui.nav)
        lines.append(f"- **Nav:** {_code(nav)}")
    for group in GROUPS:
        parts = []
        for field, grp, label, show in CONTRIBUTIONS:
            entries = getattr(plugin, field) if grp == group else ()
            factory = callable(entries)  # `cascades`: its order follows import order, so sort it
            entries = entries() if factory else entries
            if entries:
                shown = sorted(map(show, entries)) if factory else [show(e) for e in entries]
                if field == "consumer_names":
                    shown = [f"{e} (resumes at head)" if e in heads else e for e in shown]
                parts.append(f"{label} {_code(shown)}")
        if parts:
            lines.append(f"- **{group}:** " + "; ".join(parts))
    return [*lines, ""]


def _glance(modules: list[Module]) -> list[str]:
    rows = ["| Module | Kind | UI | Depends on | Weak |", "|---|---|---|---|---|"]
    for m in modules:
        deps = ", ".join(m.plugin.depends_on) or "—"
        weak = ", ".join(m.plugin.weak_depends) or "—"
        rows.append(f"| [{m.name}](#{m.name}) | {_kind(m)} | {m.ui} | {deps} | {weak} |")
    return rows


def _sockets(modules: list[Module]) -> list[str]:
    provided: dict[str, dict[str, list[str]]] = {s.value: {} for s in Socket}
    for m in modules:
        for spec in m.plugin.integrations:
            provided.setdefault(str(spec.socket), {}).setdefault(m.name, []).append(spec.name)
    readers = socket_readers()
    rows = ["| Socket | Provided by | Read by |", "|---|---|---|"]
    for socket, by in provided.items():
        names = ", ".join(f"{m} ({_code(impls)})" for m, impls in by.items()) or "—"
        rows.append(f"| `{socket}` | {names} | {', '.join(readers.get(socket, [])) or '—'} |")
    return rows


def render(modules: list[Module], notes: Notes) -> str:
    out = [
        "<!-- GENERATED by server/scripts/modules_map.py. Do not edit: change the plugin",
        f"     manifests or docs/modules-notes.md, then run: {REGENERATE} -->",
        "",
        "# Module map",
        "",
        "> **Generated.** The structure below is read from each plugin's `RaddPlugin` manifest"
        " (`server/src/radd/modules/*/__init__.py`) and `ui/package.json`; the prose comes from"
        f" [modules-notes.md](modules-notes.md). Regenerate with `{REGENERATE}`;"
        " `server/tests/test_modules_map.py` fails while this file is stale.",
        "",
    ]
    for title, text in notes.preamble.items():
        out += [f"## {title}", "", text, ""]
    out += ["## At a glance", "",
            "In load order (`Settings.modules`), then the installable plugins. **Depends on** must"
            " load first (`depends_on`); **Weak** lists modules imported only inside functions, which"
            " do not order loading (`weak_depends`). `tests/test_module_contracts.py` refuses an"
            " import declared in neither.",
            ""]
    out += [*_glance(modules), "", "## Modules", ""]
    for module in modules:
        out += _module_block(module, notes.modules[module.name])
    out += ["## Sockets", "",
            "Named interfaces one plugin provides and others read instead of importing it"
            " (`kernel/sockets.py`), so disabling a provider withdraws it. Providers come from the"
            " manifests; readers are every `Socket.X` reference in the source outside an"
            " `IntegrationSpec`.", ""]
    out += [*_sockets(modules), ""]
    for title, text in notes.sections.items():
        out += [f"## {title}", "", text, ""]
    return "\n".join(out).rstrip("\n") + "\n"


def generate() -> str:
    modules = load_modules()
    notes = parse_notes(NOTES.read_text())
    found = problems(modules, notes)
    if found:
        raise SystemExit("modules_map: fix these first:\n  " + "\n  ".join(found))
    return render(modules, notes)


def main() -> None:
    text = generate()
    MAP.write_text(text)
    print(f"wrote {MAP.relative_to(REPO)} ({len(text.encode())} bytes)")


if __name__ == "__main__":
    main()
