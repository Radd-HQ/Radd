"""Core invariants for the frontend module-federation platform (spec 94).

These lock the backend contract the SPA's runtime loader depends on: a plugin declares its UI remote
+ `ui_api_version` in its manifest, `/capabilities` surfaces every ENABLED plugin's remote, and
third-party plugins are discoverable via the `radd.plugins` entry point.
"""

from radd.config import settings
from radd.kernel import PluginUiManifest, registries
from radd.kernel.loader import load_plugins
from radd.modules.pluginmgr import discovery


def test_plugin_ui_manifest_carries_remote_and_ui_api_version():
    m = PluginUiManifest(remote="/plugins/x/remoteEntry.js", ui_api_version="1.2.0")
    assert m.remote == "/plugins/x/remoteEntry.js"
    assert m.ui_api_version == "1.2.0"
    # Defaults are empty so a nav-only plugin contributes no remote.
    assert PluginUiManifest().remote == ""


def test_participants_plugin_declares_a_federated_ui_remote():
    load_plugins(settings.modules)
    participants = registries.plugins["participants"]
    assert participants.ui is not None
    assert participants.ui.remote == "/plugins/participants/remoteEntry.js"
    assert participants.ui.ui_api_version == "1.0.0"


def test_plugin_ui_bundle_is_served_from_the_plugin_dir():
    """Colocation (spec 94): a plugin's UI bundle lives in the plugin's OWN directory; the loader
    records `<plugin dir>/ui/dist` for serving at /plugins/<name>/*."""
    load_plugins(settings.modules)
    ui_dir = registries.plugin_ui_dirs.get("participants")
    assert ui_dir is not None
    assert ui_dir.replace("\\", "/").endswith("radd/modules/participants/ui/dist")


def test_capabilities_remotes_reflect_enabled_plugins_with_ui():
    """The shape the /capabilities router builds: one remote per enabled plugin that ships UI."""
    load_plugins(settings.modules)
    remotes = {
        p.name: (p.ui.remote, p.ui.ui_api_version or "1.0.0")
        for p in registries.plugins.values()
        if p.ui is not None and p.ui.remote
    }
    assert "participants" in remotes
    assert remotes["participants"] == ("/plugins/participants/remoteEntry.js", "1.0.0")


def test_plugin_view_and_widget_types_register_and_teardown():
    """A plugin contributes view/widget TYPES (spec 94); disable removes them with everything else."""
    from radd.kernel import RaddPlugin, ViewTypeSpec, WidgetTypeSpec, registries

    p = RaddPlugin(
        id="t.types", name="t-types", version="1.0.0",
        view_types=(ViewTypeSpec(key="t.view", label="V"),),
        widget_types=(WidgetTypeSpec(key="t.widget", label="W"),),
    )
    registries.register_plugin(p)
    assert "t.view" in registries.view_types and "t.widget" in registries.widget_types
    registries.unregister_plugin(p)
    assert "t.view" not in registries.view_types and "t.widget" not in registries.widget_types


def test_disabling_a_plugin_removes_its_slq_field():
    """Disable (runtime.unmount_plugin -> registries.unregister_plugin) strips a plugin's SLQ field
    along with its nav/permissions/events — so `note ~ …` stops resolving once the plugin is off."""
    from radd.kernel import RaddPlugin, SlqFieldSpec, registries

    p = RaddPlugin(
        id="t.slq", name="t-slq", version="1.0.0",
        slq_fields=(SlqFieldSpec(name="tfield", label="T", item_ids=lambda c, v, ctx: None),),
    )
    registries.register_plugin(p)
    assert "tfield" in registries.slq_fields
    registries.unregister_plugin(p)
    assert "tfield" not in registries.slq_fields


async def test_plugin_slq_field_compiles_into_the_query():
    """A plugin can add a searchable SLQ field (spec 94): the compiler routes an unknown field name
    to `registries.slq_fields` and wraps the plugin's Select as `work_item.id IN (…)`."""
    import uuid

    from sqlalchemy import select

    from radd.db import SessionLocal
    from radd.kernel import SlqFieldSpec, registries
    from radd.modules.items.models import WorkItem
    from radd.modules.items.slq import compile_query, parse

    registries.slq_fields["xnote"] = SlqFieldSpec(
        name="xnote",
        label="X",
        item_ids=lambda contains, value, ctx: select(WorkItem.id).where(
            WorkItem.title.ilike(f"%{value}%")
        ),
    )
    try:
        async with SessionLocal() as session:
            compiled = await compile_query(
                session, parse('xnote ~ "z"'), definitions_by_key={}, current_user_id=uuid.uuid4()
            )
        sql = str(compiled.where.compile(compile_kwargs={"literal_binds": True}))
        assert "work_items.id IN (SELECT" in sql
    finally:
        registries.slq_fields.pop("xnote", None)


def test_entry_point_discovery_is_wired():
    """Third-party discovery (§10): the entry-point scan runs and folds into installable plugins.
    Tolerant of whether any external plugin happens to be installed in this environment."""
    eps = discovery.entrypoint_plugins()
    assert isinstance(eps, dict)
    # Every discovered entry is (RaddPlugin, importable-module-path).
    for pid, (plugin, path) in eps.items():
        assert plugin.id == pid
        assert isinstance(path, str) and path
    # installable_plugins() is the union of config + entry-point plugins.
    installable = discovery.installable_plugins()
    for pid in eps:
        assert pid in installable
