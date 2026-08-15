"""Kernel core-invariants (spec 93) — the plugin contract, loader, and registries.

Pure/in-memory: no DB. These pin the machinery every plugin relies on so a
regression in the loader or a registry surfaces here, not as a mystery boot failure.
"""

import pytest

from radd.config import settings
from radd.kernel import (
    KERNEL_API_VERSION,
    CapabilitySpec,
    EventTypeSpec,
    PermissionSpec,
    PluginUiManifest,
    RaddPlugin,
    load_plugins,
    registries,
)
from radd.kernel.loader import PluginLoadError, _api_compatible
from radd.kernel.registry import KernelRegistries
from radd.kernel.specs import NavItemSpec


def test_minimal_ctor_works():
    # The 49-plugin fleet constructs with just name/description/routers.
    m = RaddPlugin(name="events", description="outbox")
    assert isinstance(m, RaddPlugin)
    assert m.id == "events"  # name doubles as id
    assert m.core is True  # reclassified builtins are core
    assert m.api_version == KERNEL_API_VERSION


def test_id_defaults_to_name_but_is_overridable():
    assert RaddPlugin(name="slas").id == "slas"
    assert RaddPlugin(name="slas", id="radd.slas").id == "radd.slas"


def test_api_version_gate():
    assert _api_compatible("1.0", "1.0")
    assert _api_compatible("1.9", "1.0")  # minor is backward-compatible
    assert not _api_compatible("2.0", "1.0")  # major mismatch refused


def test_registry_aggregates_manifest_fields():
    reg = KernelRegistries()
    plugin = RaddPlugin(
        name="milestones",
        id="radd.milestones",
        core=False,
        event_types=(EventTypeSpec("milestone.created", "Milestone created", "Planning"),),
        permissions=(PermissionSpec("milestone.create", "global", "Create milestones"),),
        capabilities=(CapabilitySpec("milestones", "Milestones"),),
        ui=PluginUiManifest(nav=(NavItemSpec("milestones", "Milestones", "/milestones"),)),
    )
    reg.register_plugin(plugin)
    assert reg.event_types["milestone.created"].group == "Planning"
    assert reg.triggers()["milestone.created"].label == "Milestone created"
    assert reg.permissions["milestone.create"].scope == "global"
    assert reg.capabilities["milestones"].label == "Milestones"
    assert reg.nav[0].path == "/milestones"


def test_triggers_excludes_non_trigger_events():
    reg = KernelRegistries()
    reg.register_plugin(
        RaddPlugin(
            name="x",
            event_types=(
                EventTypeSpec("a.created", "A", "G", trigger=True),
                EventTypeSpec("a.synced", "A synced", "G", trigger=False),
            ),
        )
    )
    assert "a.created" in reg.triggers()
    assert "a.synced" not in reg.triggers()


def test_depends_on_ordering_enforced():
    with pytest.raises(PluginLoadError):
        # a plugin path whose dep isn't loaded first — simulated via a fake list is
        # awkward; instead assert the real config loads cleanly (deps satisfied).
        load_plugins(("radd.modules.items",))  # items depends on many earlier plugins


def test_real_config_loads_bootstrap_plugins():
    plugins = load_plugins(settings.modules)
    assert len(plugins) == len(settings.modules)
    # config.modules mixes foundational (core=True, locked) and optional (core=False,
    # disableable) plugins — the tracker's spine is core; integrations are optional.
    by_id = {p.id: p for p in plugins}
    for foundational in ("events", "projects", "auth", "items", "workflow", "pluginmgr"):
        assert by_id[foundational].core is True, foundational
    for optional in ("ldap", "sso", "ai", "gitlab", "pages"):
        assert by_id[optional].core is False, optional
    # every plugin registered
    assert set(registries.plugins) == {p.id for p in plugins}


# test_plugins_declare_their_own_dependencies died with the mechanism it
# asserted (RADD-1097): python_deps/js_deps were manifest fields whose promised
# install step never existed — write-only surface, deleted under the
# no-speculative-frameworks rule.
