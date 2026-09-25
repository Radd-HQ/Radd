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
