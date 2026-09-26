"""Both scheduling consumers use one arithmetic contract and their own HTTP policy."""
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from radd.exceptions import ForbiddenError, UnauthorizedError
from radd.modules.auth.deps import optional_user
from radd.modules.backup.router import router as backup_router
from radd.schedule import next_run
from radd.schedule_preview import SchedulePreviewRequest, preview_schedule


@pytest.mark.parametrize('config', [
    {'kind': 'interval', 'minutes': 7},
    {'kind': 'daily', 'time': '09:00'},
    {'kind': 'weekly', 'time': '09:00', 'weekdays': [0, 4]},
    {'kind': 'monthly', 'time': '09:00', 'day': 31},
    {'kind': 'cron', 'expression': '0 9 * * 1'},
])
def test_preview_matches_each_scheduler_occurrence_in_its_timezone(config):
    now = datetime(2026, 10, 30, 12)
    result = preview_schedule(SchedulePreviewRequest(**config), 'America/New_York', now=now)
    assert result.error is None
    assert result.timezone == 'America/New_York'
    assert len(result.next_runs) == 5
    for actual in result.next_runs:
        now = next_run(config, now, result.timezone)
        assert actual == now
    assert all(iso.endswith('Z') for iso in result.model_dump(mode='json')['next_runs'])


@pytest.mark.parametrize('config', [
    {'kind': 'interval', 'minutes': 1},
    {'kind': 'weekly', 'time': '09:00', 'weekdays': []},
    {'kind': 'monthly', 'time': '09:00', 'day': 32},
    {'kind': 'daily', 'time': '25:00'},
    {'kind': 'cron', 'expression': '* * * * *'},
    {'kind': 'cron', 'expression': '0 0 31 2 *'},
    {'kind': 'future-kind'},
])
def test_invalid_schedules_return_no_partial_occurrences(config):
    result = preview_schedule(SchedulePreviewRequest(**config), 'UTC')
    assert result.error
    assert result.next_runs == []


@pytest.mark.parametrize(('role', 'expected'), [('admin', 200), ('member', 403), (None, 401)])
async def test_backup_preview_without_automation_routes_and_with_own_permissions(role, expected):
    # Only the actual backup router is mounted: no automation route can answer.
    app = FastAPI()
    app.include_router(backup_router)
    app.dependency_overrides[optional_user] = lambda: SimpleNamespace(instance_role=role) if role else None
    for exception, status in [(ForbiddenError, 403), (UnauthorizedError, 401)]:
        async def handler(request, exc, code=status):
            return JSONResponse({'detail': str(exc)}, status_code=code)
        app.add_exception_handler(exception, handler)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/backups/schedule/preview', json={'kind': 'interval', 'minutes': 7})
        assert response.status_code == expected, response.text
        assert (await client.post('/automations/schedule/preview', json={})).status_code == 404
        if expected == 200:
            assert len(response.json()['next_runs']) == 5
            refused = await client.post('/backups/schedule/preview', json={'kind': 'interval', 'minutes': 1})
            assert refused.status_code == 200
            assert refused.json()['error']
            assert refused.json()['next_runs'] == []
