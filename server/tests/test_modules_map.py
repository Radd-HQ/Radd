"""docs/modules.md is generated (server/scripts/modules_map.py): the structure from the plugin
manifests, the prose from docs/modules-notes.md. Pinned the way plugin-boundaries.test.mjs pins
the derived SDK shim, so a manifest change without a regenerated map fails here, and the prose
cannot grow back into a changelog."""

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "modules_map.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("modules_map", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


modules_map = _load_generator()


def _inputs():
    return modules_map.load_modules(), modules_map.parse_notes(modules_map.NOTES.read_text())


def test_the_checked_in_map_is_the_generators_output():
    assert modules_map.MAP.read_text() == modules_map.generate(), (
        f"docs/modules.md is stale; run: {modules_map.REGENERATE}"
    )


def test_every_plugin_has_one_capped_paragraph_and_no_changelog():
    modules, notes = _inputs()
    assert modules_map.problems(modules, notes) == []
    assert {m.name for m in modules} == set(notes.modules)


def test_the_checks_bite():
    """Each rule above refuses its violation (a check that cannot fail proves nothing)."""
    modules, notes = _inputs()
    name = modules[0].name
    too_long = "x" * (modules_map.MODULE_CAP + 1)
    cases = {
        "characters (cap": {**notes.modules, name: too_long},
        "write one paragraph": {**notes.modules, name: "one\n\ntwo"},
        "issue keys": {**notes.modules, name: "Fixed in RADD-1."},
        "no paragraph": {k: v for k, v in notes.modules.items() if k != name},
        "not a plugin": {**notes.modules, "no_such_module": "text"},
    }
    for expected, paragraphs in cases.items():
        found = modules_map.problems(modules, replace(notes, modules=paragraphs))
        assert any(expected in problem for problem in found), (expected, found)
    long_section = replace(notes, sections={"Rules": "x" * (modules_map.SECTION_CAP + 1)})
    assert any("cap" in problem for problem in modules_map.problems(modules, long_section))
