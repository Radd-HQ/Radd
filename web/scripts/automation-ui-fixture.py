"""Browser fixtures use the actual registered automation catalog and templates.

No connection or writes: an unscoped instance admin passes permission checks
before any database operation. Browser transports provide isolated sample rows.
"""
import asyncio
import importlib
import json

from radd.config import settings
from radd.kernel import load_plugins
from radd.modules.auth.models import User


async def main():
    load_plugins(settings.modules)
    router = importlib.import_module("radd.modules.automations.router")
    user = User(instance_role="admin", active=True, email="fixture@example.test", name="Fixture")
    catalog = await router.get_catalog(None, user)
    templates = await router.list_templates(None, user)
    print(json.dumps({"catalog": catalog.model_dump(mode="json"),
                      "templates": [template.model_dump(mode="json") for template in templates]}))


asyncio.run(main())
