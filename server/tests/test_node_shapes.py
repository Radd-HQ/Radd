"""RADD-1325: the server answers a node's ports and outputs for given params, so
the editor never recomputes a plugin node's shape in core code."""

import importlib
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import NotFoundError
from radd.kernel import load_plugins
from radd.kernel.registry import registries
from radd.modules.auth.models import User
from radd.modules.automations.schemas import NodeShapeRequest

router = importlib.import_module("radd.modules.automations.router")


@pytest.fixture
async def admin():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        user = User(email=f"shape-{uuid.uuid4().hex[:8]}@example.com", name="Shape", instance_role="admin")
        session.add(user)
        await session.flush()
        yield user
        await session.rollback()
    await engine.dispose()


async def test_a_classifiers_ports_are_its_answers_plus_the_fallback(admin):
    load_plugins(settings.modules)
    shape = await router.node_shape("ai.classify", NodeShapeRequest(params={"answers": ["bug", "feature"]}), admin)
    assert shape.ports == ["bug", "feature", "unavailable"]
    assert [o.name for o in shape.outputs] == ["answer"]


async def test_a_scripts_outputs_are_the_keys_it_declares(admin):
    load_plugins(settings.modules)
    shape = await router.node_shape("script.run", NodeShapeRequest(params={"outputs": ["score", "reason"]}), admin)
    assert [o.name for o in shape.outputs] == ["score", "reason"]


async def test_a_terminal_node_has_no_ports_and_an_unknown_type_is_404(admin):
    load_plugins(settings.modules)
    assert (await router.node_shape("verdict.block", NodeShapeRequest(params={}), admin)).ports == []
    with pytest.raises(NotFoundError):
        await router.node_shape("nope.nothing", NodeShapeRequest(params={}), admin)


def test_the_catalog_flags_exactly_the_params_dependent_nodes():
    load_plugins(settings.modules)
    dynamic = {k for k, s in registries.automation_nodes.items() if s.dynamic_ports or s.dynamic_outputs}
    assert {"ai.classify", "ai.generate", "script.run", "script.decide"} <= dynamic
    # Fixed-shape and terminal nodes are not asked about.
    assert not ({"action.create_item", "gate.payload", "verdict.block"} & dynamic)


async def test_catalog_names_actual_owners_and_withdraws_disabled_nodes(admin):
    load_plugins(settings.modules)
    result = await router.get_catalog(None, admin)
    owners = {node.key: node.plugin for node in result.nodes}
    assert owners["ai.classify"] == "ai"
    assert owners["script.run"] == "scripts"
    assert owners["verdict.block"] == "automations"
    scripts = next(plugin for plugin in registries.plugins.values() if plugin.name == "scripts")
    try:
        registries.unregister_plugin(scripts)
        withdrawn = await router.get_catalog(None, admin)
        assert not any(node.plugin == "scripts" for node in withdrawn.nodes)
    finally:
        registries.register_plugin(scripts)
    restored = await router.get_catalog(None, admin)
    assert sum(node.key == "script.run" for node in restored.nodes) == 1
