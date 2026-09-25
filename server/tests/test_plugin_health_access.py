"""The contributed mail health card must retain the operator-only data boundary."""
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from radd.exceptions import ForbiddenError
from radd.modules.mailintake.transport import MailHealth

router = importlib.import_module("radd.modules.mailintake.router")


async def test_mail_health_checks_admin_before_querying(monkeypatch):
    query = AsyncMock(return_value=MailHealth(24, 0, 0, False, ()))
    monkeypatch.setattr(router.service, "mail_health", query)
    monkeypatch.setattr(router.authz, "is_instance_admin", lambda user: user.admin)
    with pytest.raises(ForbiddenError):
        await router.outbound_health(None, SimpleNamespace(admin=False))
    query.assert_not_awaited()
    result = await router.outbound_health(None, SimpleNamespace(admin=True))
    assert result.failures == 0
    query.assert_awaited_once_with(None)
