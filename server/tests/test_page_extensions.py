"""Page extensions (RADD-709) — the registry, and the contract across the wire.

The interesting invariant is not that a dataclass holds fields; it is that the
kernel's DECLARED set and the SPA's RENDERED set do not drift. They live in
different languages and are edited in different files, and the failure is silent
in both directions:

  - declared but not rendered -> the insert menu offers something that renders
    as "unknown extension";
  - rendered but not declared -> a working block nobody can discover.

So this reads the TypeScript registration list and compares it to the kernel's.
"""

import re
from pathlib import Path

import pytest

from radd.kernel.registry import registries
from radd.modules.pages import plugin as pages_plugin
from radd.modules.pages.extensions import PAGE_EXTENSIONS
from radd.modules.pages.types import PageExtensionName

WEB_EXTENSIONS = (
    Path(__file__).resolve().parents[2] / "web/src/components/pages/extensions.tsx"
)


@pytest.fixture(autouse=True)
def registered():
    registries.register_plugin(pages_plugin)
    yield


def test_the_plugin_contributes_its_extensions_to_the_kernel():
    assert {spec.name for spec in PAGE_EXTENSIONS} <= set(registries.page_extensions)
    assert registries.page_extensions["toc"].label == "Table of contents"


def test_disabling_the_plugin_removes_them():
    """The insert menu is a function of what is MOUNTED — a disabled plugin's
    extensions must leave the catalog, not linger as dead entries."""
    registries.unregister_plugin(pages_plugin)
    assert not any(name in registries.page_extensions for name in PageExtensionName)
    registries.register_plugin(pages_plugin)  # restore for the rest of the module


def test_every_declared_name_is_a_member_of_the_enum():
    """The fence suffix is a WIRE FORMAT: it sits in page bodies in the database.
    Keeping every one in a StrEnum is what makes renaming one visibly a data
    migration rather than a rename."""
    assert {spec.name for spec in PAGE_EXTENSIONS} == {e.value for e in PageExtensionName}


def _web_registered_names() -> set[str]:
    source = WEB_EXTENSIONS.read_text()
    # The registry entries are `name: "toc",` inside the EXTENSIONS array.
    body = source[source.index("const EXTENSIONS"):]
    return set(re.findall(r'^\s*name:\s*"([a-z][a-z0-9-]*)"', body, re.MULTILINE))


def test_the_spa_renders_nothing_the_kernel_has_not_declared():
    """A block the SPA can render but the kernel never declares is undiscoverable:
    it works only for someone who already knows to type the fence by hand."""
    declared = {spec.name for spec in PAGE_EXTENSIONS}
    assert _web_registered_names() <= declared


def test_the_kernel_declares_nothing_the_spa_cannot_render():
    """The other direction, and the one that produces a visibly broken product:
    the insert menu offering an entry that lands as an "unknown extension" card."""
    declared = {spec.name for spec in PAGE_EXTENSIONS}
    assert declared <= _web_registered_names()
