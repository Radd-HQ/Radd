"""Page extensions (RADD-709): the kernel's DECLARED set and the SPA's RENDERED
set must not drift, and the failure is silent both ways (declared-only renders as
"unknown extension"; rendered-only is undiscoverable). So this reads the
TypeScript registration list and compares it to the kernel's.
"""

import re
from pathlib import Path

import pytest

from radd.kernel.registry import registries
from radd.modules.pages import plugin as pages_plugin
from radd.modules.pages.extensions import PAGE_EXTENSIONS
from radd.modules.pages.types import PageExtensionName

#: The wiki's UI is the pages plugin's bundled package (RADD-1392).
WEB_PAGES = Path(__file__).resolve().parents[1] / "src/radd/modules/pages/ui/src"
#: What gets REGISTERED: the eager registry declares every first-party block, so a
#: `radd:*` fence renders wherever markdown does (an issue description too).
WEB_REGISTRY = WEB_PAGES / "extension-registry.tsx"
#: What RENDERS them: the renderer maps load with the first block. A set may live in
#: its own module (spec 117 split the importers' blocks out to keep a file under the
#: size limit); both are scanned, so a split cannot silently drop half the set.
WEB_RENDERER_FILES = (
    WEB_PAGES / "view/extensions.tsx",
    WEB_PAGES / "view/ImportExtensions.tsx",
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


#: Where each renderer file's map starts. Anything before it is component code.
_RENDERER_MARKERS = ("const RENDERERS", "const IMPORT_RENDERERS")


def _web_registered_names() -> set[str]:
    """The registry's entries: `firstParty("toc", …)` inside `const EXTENSIONS`."""
    source = WEB_REGISTRY.read_text()
    assert "const EXTENSIONS" in source, "the registry declares no page-extension array"
    body = source[source.index("const EXTENSIONS"):]
    return set(re.findall(r'^\s*firstParty\("([a-z][a-z0-9-]*)"', body, re.MULTILINE))


def _web_rendered_names() -> set[str]:
    """The renderer maps' keys: `toc: (params) =>` or `"label-list": (params) =>`."""
    names: set[str] = set()
    for path in WEB_RENDERER_FILES:
        source = path.read_text()
        starts = [source.index(m) for m in _RENDERER_MARKERS if m in source]
        assert starts, f"{path.name} declares no renderer map"
        body = source[min(starts):]
        names |= set(re.findall(r'^\s*"?([a-z][a-z0-9-]*)"?:\s*\(', body, re.MULTILINE))
    return names


def test_the_spa_renders_nothing_the_kernel_has_not_declared():
    """A block the SPA can render but the kernel never declares is undiscoverable:
    it works only for someone who already knows to type the fence by hand."""
    declared = {spec.name for spec in PAGE_EXTENSIONS}
    assert _web_registered_names() <= declared
    assert _web_rendered_names() <= declared


def test_the_kernel_declares_nothing_the_spa_cannot_render():
    """The other direction, and the one that produces a visibly broken product:
    the insert menu offering an entry that lands as an "unknown extension" card —
    or, registered without a renderer, as an empty block."""
    declared = {spec.name for spec in PAGE_EXTENSIONS}
    assert declared <= _web_registered_names()
    assert declared <= _web_rendered_names()


# --- where an extension came from (RADD-748) ---------------------------------
#
# The insert menu groups built-ins apart from what a plugin contributed. Nothing
# shipped contributes a page extension from a NON-core plugin yet, so these
# mount a stand-in: the registry path they exercise — record the source on
# register, drop it on unregister — is the same one a real plugin would take,
# and it is the half the SPA cannot verify for itself.


def _stand_in_plugin():
    from radd.kernel import PageExtensionSpec, RaddPlugin

    return RaddPlugin(
        name="acme-notes",
        description="Acme Notes",
        core=False,
        page_extensions=(
            PageExtensionSpec(name="acme-note", label="Acme note", icon="sparkles"),
        ),
    )


def test_a_plugins_extension_records_which_plugin_contributed_it():
    plugin = _stand_in_plugin()
    registries.register_plugin(plugin)
    try:
        assert registries.page_extension_sources["acme-note"].plugin == "acme-notes"
        # And the first-party ones still name theirs, so the menu can separate
        # the two without the client guessing from names it has never seen.
        assert registries.page_extension_sources["toc"].plugin == "pages"
    finally:
        registries.unregister_plugin(plugin)


def test_disabling_a_plugin_forgets_where_its_extension_came_from():
    """A stale source outlives its spec and would label the NEXT extension that
    reuses the name with a plugin that is no longer mounted."""
    plugin = _stand_in_plugin()
    registries.register_plugin(plugin)
    registries.unregister_plugin(plugin)
    assert "acme-note" not in registries.page_extensions
    assert "acme-note" not in registries.page_extension_sources
