"""The public SDK surface + api_version gate (spec 93 / A5, docs/plugin-platform.md §9).

`radd.sdk` is the only import a plugin needs; the loader refuses a plugin whose
`api_version` major is incompatible with the kernel.
"""

import sys
import types

import pytest

from radd import sdk
from radd.config import settings
from radd.kernel import RaddPlugin
from radd.kernel.loader import PluginLoadError, load_plugins


def test_kernel_surface_is_eagerly_available():
    # contract + specs + register_* + Base/session — no import gymnastics for a plugin
    for name in (
        "RaddPlugin", "EntitySpec", "EventTypeSpec", "CapabilitySpec", "PermissionSpec",
        "CrudResourceSpec", "NavItemSpec", "PluginUiManifest", "TaskSpec", "IntegrationSpec",
        "register_permission", "register_crud_resource", "register_event_type",
        "register_capability", "register_integration", "registries", "Base", "get_session",
        "API_VERSION",
    ):
        assert hasattr(sdk, name), name


def test_data_sdk_names_resolve_lazily_to_real_callables():
    # acting-user-scoped services, resolved on access (PEP 562)
    assert callable(sdk.get_item)
    assert callable(sdk.list_items)
    assert callable(sdk.list_comments)
    assert callable(sdk.list_projects)
    assert callable(sdk.effective_permissions)
    assert callable(sdk.emit_event)
    assert callable(sdk.resolve_setting)
    assert callable(sdk.register_access_resource)
    # Permission is the enum type
    assert sdk.Permission.ITEM_READ.value == "item.read"


def test_unknown_sdk_attribute_raises():
    with pytest.raises(AttributeError):
        _ = sdk.definitely_not_a_real_sdk_symbol


def test_loader_refuses_incompatible_api_version():
    mod = types.ModuleType("fake_incompat_plugin")
    mod.plugin = RaddPlugin(name="fake_incompat", api_version="99.0")
    sys.modules["fake_incompat_plugin"] = mod
    try:
        with pytest.raises(PluginLoadError):
            load_plugins(("fake_incompat_plugin",))
    finally:
        del sys.modules["fake_incompat_plugin"]
        load_plugins(settings.modules)  # restore the registry for later tests
