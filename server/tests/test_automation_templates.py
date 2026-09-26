"""RADD-1316: every registered automation template is listed and can be saved
exactly as offered — a template that opens as an unsaveable graph would make
"from template" a trap. Each is created DISABLED, as the editor creates it."""

import importlib
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.kernel import load_plugins
from radd.kernel.registry import registries
from radd.modules.auth.models import User
from radd.modules.automations import service as automations, templates
from radd.modules.automations.schemas import RuleCreate

router = importlib.import_module("radd.modules.automations.router")


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(email=f"tpl-{uuid.uuid4().hex[:8]}@example.com", name="Templates", instance_role="admin")
    db.add(user)
    await db.flush()
    return user


async def test_every_template_is_listed_and_saveable_as_offered(db, admin):
    load_plugins(settings.modules)
    listed = {t.key: t for t in await router.list_templates(db, admin)}
    assert listed, "no templates registered"
    assert set(listed) == {key for key, t in registries.automation_templates.items() if templates.available(t)}
    for template in listed.values():
        rule = await automations.create_rule(
            db,
            RuleCreate.model_validate({
                "name": template.name, "enabled": False, "nodes": template.nodes, "edges": template.edges,
            }),
            admin.id,
        )
        assert rule.enabled is False, template.key


def test_a_template_naming_a_missing_node_type_is_not_available():
    from radd.kernel.specs import AutomationTemplateSpec

    load_plugins(settings.modules)
    ghost = AutomationTemplateSpec(
        key="ghost", name="Ghost", description="",
        nodes=({"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": "item.created"}},
               {"id": "a", "kind": "action", "type": "uninstalled.node", "params": {}}),
    )
    assert templates.available(ghost) is False


async def test_catalog_and_templates_report_actual_registry_owners(db, admin):
    """Display groups and key prefixes are not ownership contracts."""
    load_plugins(settings.modules)
    event_owners = {
        event.event_type: plugin.name
        for plugin in registries.plugins.values()
        for event in plugin.event_types
    }
    template_owners = {
        template.key: plugin.name
        for plugin in registries.plugins.values()
        for template in plugin.automation_templates
    }
    result = await router.get_catalog(db, admin)
    assert result.triggers
    for trigger in result.triggers:
        assert trigger.plugin == event_owners[trigger.event_type]
    listed = await router.list_templates(db, admin)
    assert listed
    for template in listed:
        assert template.plugin == template_owners[template.key]
    # A display group is not the owner: automations' own templates group as
    # "Issues"/"Chat" and still report the automations plugin.
    assert any(template.plugin == "automations" and template.group != "Automations" for template in listed)


async def test_withdrawn_owner_disappears_from_catalog_and_templates(db, admin):
    load_plugins(settings.modules)
    plugin = registries.plugins["github"]
    before = await router.get_catalog(db, admin)
    assert any(trigger.plugin == "github" for trigger in before.triggers)
    registries.unregister_plugin(plugin)
    try:
        after = await router.get_catalog(db, admin)
        assert not any(trigger.plugin == "github" for trigger in after.triggers)
        assert not any(template.plugin == "github" for template in await router.list_templates(db, admin))
    finally:
        registries.register_plugin(plugin)


async def test_catalog_owns_entity_derived_triggers(db, admin):
    """RADD-1371: an EntitySpec plugin's derived events (milestone.created …)
    are triggers with an owner — the catalog 500'd on them with Milestones on."""
    load_plugins((*settings.modules, "radd.modules.milestones"))
    try:
        assert "radd.milestones" in registries.plugins
        result = await router.get_catalog(db, admin)
        owned = {trigger.event_type: trigger.plugin for trigger in result.triggers}
        assert owned.get("milestone.created") == "milestones"
    finally:
        load_plugins(settings.modules)
