"""RADD-1341: real route lifecycles, draining, failures, and process convergence."""
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from radd.kernel import RaddPlugin, registries
from radd.kernel import runtime
from radd.kernel.specs import TaskSpec, EventTypeSpec, EntitySpec, EntityFieldSpec
from radd.modules.pluginmgr import live, service


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr(runtime, 'gate', runtime.RuntimeGate())
    monkeypatch.setattr(live, 'gate', runtime.gate)
    app = FastAPI()
    app.add_middleware(runtime.RuntimeMiddleware)
    manager = runtime.PluginRuntime(app)
    manager.route_end = len(app.routes)
    @app.get('/{path:path}')
    async def fallback(path):
        return {'fallback': path}
    return app, manager


def package(monkeypatch, plugin):
    path = 'fixture_live_plugin'
    monkeypatch.setitem(sys.modules, path, SimpleNamespace(plugin=plugin))
    return path


async def test_routes_hooks_tasks_and_catalog_toggle_repeatedly(harness, monkeypatch):
    app, manager = harness
    router = APIRouter()
    @router.get('/live-fixture')
    async def route():
        return {'live': True}
    start, stop = AsyncMock(), AsyncMock()
    loop = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    backend = SimpleNamespace(schedule=lambda *a, **kw: loop)
    monkeypatch.setattr('radd.kernel.sockets.provider', lambda *a: backend)
    plugin = RaddPlugin(name='live-fixture', core=False, routers=(router,),
                        on_startup=(start,), on_shutdown=(stop,),
                        tasks=(TaskSpec(name='fixture-job', run=AsyncMock(), interval=60),),
                        event_types=(EventTypeSpec('fixture.event', 'Fixture event', 'Fixture'),))
    path = package(monkeypatch, plugin)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for _ in range(2):
            await manager.enable(plugin, path)
            assert (await client.get('/api/v1/live-fixture')).json() == {'live': True}
            assert 'fixture.event' in registries.triggers()
            await manager.disable(plugin)
            assert 'fallback' in (await client.get('/api/v1/live-fixture')).json()
            assert 'fixture.event' not in registries.triggers()
    assert start.await_count == stop.await_count == 2
    assert loop.start.await_count == loop.stop.await_count == 2
    assert not manager.routes and not manager.loops


async def test_disable_drains_request_and_refuses_new_plugin_work(harness, monkeypatch):
    app, manager = harness
    entered, finish = asyncio.Event(), asyncio.Event()
    router = APIRouter()
    @router.post('/slow-plugin')
    async def slow():
        entered.set()
        await finish.wait()
        assert 'slow-plugin' in registries.plugins
        return {'committed': True}
    plugin = RaddPlugin(name='slow-plugin', core=False, routers=(router,))
    await manager.enable(plugin, package(monkeypatch, plugin))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        request = asyncio.create_task(client.post('/api/v1/slow-plugin'))
        await entered.wait()
        disabling = asyncio.create_task(manager.disable(plugin))
        await asyncio.sleep(0)
        assert not disabling.done()
        assert (await client.post('/api/v1/slow-plugin')).status_code == 503
        # Unrelated HTTP remains available while draining.
        assert (await client.get('/unrelated')).status_code == 200
        finish.set()
        assert (await request).json() == {'committed': True}
        await disabling
    assert plugin.id not in registries.plugins


async def test_failed_startup_removes_partial_routes_and_stops_hooks(harness, monkeypatch):
    app, manager = harness
    stop = AsyncMock()
    router = APIRouter()
    @router.get('/broken-plugin')
    async def route():
        return True
    plugin = RaddPlugin(name='broken-plugin', core=False, routers=(router,),
                        on_startup=(AsyncMock(side_effect=RuntimeError('startup failed')),),
                        on_shutdown=(stop,))
    with pytest.raises(RuntimeError, match='startup failed'):
        await manager.enable(plugin, package(monkeypatch, plugin))
    assert plugin.id not in registries.plugins
    assert plugin.id not in manager.routes
    stop.assert_awaited_once()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert 'fallback' in (await client.get('/api/v1/broken-plugin')).json()


async def test_spawned_job_is_drained_and_worker_tick_pauses(harness):
    from radd.worker import PeriodicLoop
    entered, finish = asyncio.Event(), asyncio.Event()
    async def job():
        entered.set()
        await finish.wait()
    task = runtime.spawn(job())
    await entered.wait()
    changed = asyncio.Event()
    async def swap():
        async with runtime.gate.change('fixture'):
            changed.set()
    swap_task = asyncio.create_task(swap())
    await asyncio.sleep(0)
    tick = AsyncMock()
    loop = PeriodicLoop(tick, interval=lambda: .01, name='fixture', enabled=lambda: True)
    await loop.start()
    await asyncio.sleep(.03)
    assert not changed.is_set()
    tick.assert_not_awaited()
    finish.set()
    await task
    await swap_task
    await asyncio.sleep(.03)
    await loop.stop()
    assert tick.await_count > 0


async def test_cancelled_before_start_job_releases_admission(harness):
    task = runtime.spawn(asyncio.sleep(100))
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert runtime.gate.count == 0


async def test_entity_contributions_removed_without_deleting_tables(harness, monkeypatch):
    _, manager = harness
    entity = EntitySpec(key='live_note', table='test_live_notes', label='Live note', plural='live_notes',
                        fields=(EntityFieldSpec(name='title', type='str'),))
    plugin = RaddPlugin(name='live-entity', core=False, entities=(entity,))
    await manager.enable(plugin, package(monkeypatch, plugin))
    assert 'live_note' in registries.entity_refs
    await manager.disable(plugin)
    assert 'live_note' not in registries.entity_refs
    assert 'live_note' not in registries.crud_resources
    assert not any(k.startswith('live_note.') for k in registries.event_types)
    from radd.kernel.entities import build_model
    assert build_model(entity).__table__ is not None


async def test_peer_pending_and_error_not_misreported_as_disabled(monkeypatch):
    plugin = RaddPlugin(name='peer-plugin', core=False)
    monkeypatch.setattr('radd.modules.pluginmgr.discovery.core_plugins', lambda: {})
    monkeypatch.setattr('radd.modules.pluginmgr.discovery.installable_plugins', lambda: {plugin.id:(plugin,'fixture')})
    monkeypatch.setattr(service, '_states', AsyncMock(return_value={plugin.id:SimpleNamespace(state='disabled',version='1')}))
    peer = {'process':'worker', 'active':[plugin.id], 'observed':[], 'versions':{plugin.id:'disabled:'}, 'stale':False}
    monkeypatch.setattr(live, 'cluster_reports', AsyncMock(return_value=[peer]))
    row = (await service.list_plugins(AsyncMock()))[0]
    assert row.runtime_state == 'applying' and row.pending_processes == 1
    peer['errors'] = {plugin.id:'Shutdown failed'}
    row = (await service.list_plugins(AsyncMock()))[0]
    assert row.runtime_state == 'error' and row.runtime_errors == ('Shutdown failed',)
    peer.update(active=[], errors={})
    assert (await service.list_plugins(AsyncMock()))[0].runtime_state == 'disabled'


async def test_drain_timeout_never_cancels_running_work(harness):
    runtime.gate.drain_timeout = .01
    finish = asyncio.Event()
    job = runtime.spawn(finish.wait())
    with pytest.raises(TimeoutError):
        async with runtime.gate.change('busy'):
            pytest.fail('Mutated runtime before draining')
    assert not job.done()
    assert not runtime.gate.changing and not runtime.gate.blocked
    finish.set()
    await job


async def test_expired_process_lease_stops_admissions(harness):
    app, _ = harness
    runtime.gate.lease_until = 0
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/unrelated')).status_code == 503
    called = AsyncMock()
    with pytest.raises(RuntimeError, match='lease expired'):
        async with runtime.gate.work(background=True):
            await called()
    called.assert_not_awaited()


async def test_shutdown_failure_remains_visible_and_retryable(harness, monkeypatch):
    _, manager = harness
    stop = AsyncMock(side_effect=RuntimeError('not stopped'))
    plugin = RaddPlugin(name='failed-stop', core=False, on_shutdown=(stop,))
    await manager.enable(plugin, package(monkeypatch, plugin))
    with pytest.raises(RuntimeError, match='not stopped'):
        await manager.disable(plugin)
    assert plugin.id in registries.plugins
    stop.side_effect = None
    await manager.disable(plugin)
    assert plugin.id not in registries.plugins


async def test_shared_database_requires_both_process_acknowledgements(monkeypatch):
    from datetime import UTC, datetime, timedelta
    from radd.db import SessionLocal
    from radd.modules.pluginmgr.models import PluginProcess
    plugin = RaddPlugin(name='two-replicas', core=False)
    monkeypatch.setattr('radd.modules.pluginmgr.discovery.core_plugins', lambda: {})
    monkeypatch.setattr('radd.modules.pluginmgr.discovery.installable_plugins', lambda: {plugin.id:(plugin,'fixture')})
    monkeypatch.setattr(service, '_states', AsyncMock(return_value={plugin.id:SimpleNamespace(state='disabled',version='1')}))
    async with SessionLocal() as session:
        now = datetime.now(UTC).replace(tzinfo=None)
        web = PluginProcess(process_id='test-web', updated_at=now,
                            report={'process':'test-web','active':[], 'observed':[], 'versions':{plugin.id:'disabled:'}})
        worker = PluginProcess(process_id='test-worker', updated_at=now,
                               report={'process':'test-worker','active':[plugin.id], 'observed':[], 'versions':{plugin.id:'disabled:'}})
        session.add_all([web, worker])
        await session.flush()
        row = (await service.list_plugins(session))[0]
        assert row.runtime_state == 'applying' and row.pending_processes == 1
        worker.report = {**worker.report, 'active':[]}
        await session.flush()
        assert (await service.list_plugins(session))[0].runtime_state == 'disabled'
        worker.report = {**worker.report, 'active':[plugin.id]}
        worker.updated_at = now - timedelta(seconds=31)
        await session.flush()
        assert (await service.list_plugins(session))[0].runtime_state == 'disabled'
        assert next(r for r in await live.cluster_reports(session) if r['process']=='test-worker')['stale']
        await session.rollback()


async def test_plugin_websocket_closes_and_shutdown_flushes(harness, monkeypatch):
    from fastapi import WebSocket
    app, manager = harness
    router = APIRouter()
    connected = asyncio.Event()
    @router.websocket('/live-socket')
    async def socket(websocket: WebSocket):
        await websocket.accept()
        connected.set()
        await websocket.receive_text()
    flush = AsyncMock()
    plugin = RaddPlugin(name='live-socket', core=False, routers=(router,), on_shutdown=(flush,))
    await manager.enable(plugin, package(monkeypatch, plugin))
    queue = asyncio.Queue()
    await queue.put({'type':'websocket.connect'})
    messages = []
    async def send(message):
        messages.append(message)
    scope = {'type':'websocket','asgi':{'version':'3.0'},'path':'/api/v1/live-socket',
             'root_path':'','scheme':'ws','headers':[],'query_string':b'',
             'server':('test',80),'client':('test',1),'subprotocols':[]}
    connection = asyncio.create_task(app(scope, queue.get, send))
    await asyncio.wait_for(connected.wait(), 2)
    await manager.disable(plugin)
    await asyncio.gather(connection, return_exceptions=True)
    assert {'type':'websocket.close','code':1012} in messages
    flush.assert_awaited_once()
    assert not runtime.gate.sockets


async def test_expired_lease_rejects_websocket_connections_and_messages(harness):
    received = []
    messages = []
    async def app(scope, receive, send):
        received.append(await receive())
    async def send(message):
        messages.append(message)
    async def receive():
        # Lease expires while an existing connection waits for its next message.
        runtime.gate.lease_until = 0
        return {'type':'websocket.receive', 'text':'new work'}
    middleware = runtime.RuntimeMiddleware(app)
    await middleware({'type':'websocket'}, receive, send)
    assert received == [{'type':'websocket.disconnect', 'code':1013}]
    received.clear()
    await middleware({'type':'websocket'}, receive, send)
    assert not received
    assert messages[-1] == {'type':'websocket.close', 'code':1013}


async def test_previous_toggle_ack_cannot_complete_a_new_request(monkeypatch):
    plugin = RaddPlugin(name='revision-check', core=False)
    monkeypatch.setattr('radd.modules.pluginmgr.discovery.core_plugins', lambda: {})
    monkeypatch.setattr('radd.modules.pluginmgr.discovery.installable_plugins', lambda: {plugin.id:(plugin,'fixture')})
    row = SimpleNamespace(state='disabled', version='1', updated_at='new-request')
    monkeypatch.setattr(service, '_states', AsyncMock(return_value={plugin.id:row}))
    peer = {'active':[], 'observed':[], 'stale':False, 'versions':{plugin.id:'disabled:previous-request'}}
    monkeypatch.setattr(live, 'cluster_reports', AsyncMock(return_value=[peer]))
    assert (await service.list_plugins(AsyncMock()))[0].runtime_state == 'applying'
    peer['versions'][plugin.id] = live.state_version(row)
    assert (await service.list_plugins(AsyncMock()))[0].runtime_state == 'disabled'
