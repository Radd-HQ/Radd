"""RADD-1341/1372: route lifecycles, per-owner draining, failures, and the lease."""
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from radd.kernel import RaddPlugin, admission, registries, runtime
from radd.kernel.specs import TaskSpec, EventTypeSpec, EntitySpec, EntityFieldSpec
from radd.worker import PeriodicLoop


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr(admission, 'gate', admission.RuntimeGate())
    app = FastAPI()
    app.add_middleware(runtime.RuntimeMiddleware)
    manager = runtime.PluginRuntime(app)
    manager.route_end = len(app.routes)
    @app.get('/{path:path}')
    async def fallback(path):
        return {'fallback': path}
    return app, manager


def package(monkeypatch, plugin):
    path = f"fixture_{plugin.name.replace('-', '_')}"
    monkeypatch.setitem(sys.modules, path, SimpleNamespace(plugin=plugin))
    return path


def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')


def slow_plugin(name):
    """A plugin whose POST blocks until released — a long import, an SSE stream."""
    entered, finish = asyncio.Event(), asyncio.Event()
    router = APIRouter()
    @router.post(f'/{name}')
    async def slow():
        entered.set()
        await finish.wait()
        assert name in registries.plugins  # never torn down underneath its own request
        return {'committed': True}
    @router.get(f'/{name}')
    async def quick():
        return {'plugin': name}
    return RaddPlugin(name=name, core=False, routers=(router,)), entered, finish


def ticking_plugin(name, ticks):
    """A plugin that starts a PeriodicLoop from on_startup, as the dispatchers do."""
    async def tick():
        ticks.append(name)
    loop = PeriodicLoop(tick, interval=lambda: .005, name=name, enabled=lambda: True)
    return RaddPlugin(name=name, core=False, on_startup=(loop.start,), on_shutdown=(loop.stop,))


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
    async with client_for(app) as client:
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


async def test_every_periodic_taskspec_is_scheduled_with_a_gate():
    """RADD-872, on the path that runs them now (`start_plugin`)."""
    scheduled = []
    backend = SimpleNamespace(schedule=lambda name, run, interval, gate=None:
                              scheduled.append((name, gate)) or object())
    loops = [loop for plugin in registries.plugins.values()
             for loop in runtime.schedule_tasks(plugin, backend)]
    assert 'access.expiry-sweep' in [name for name, _ in scheduled]
    periodic = [s for s in registries.tasks.values() if s.interval is not None]
    assert len(loops) == len(periodic) == len(scheduled)
    assert all(gate is not None for _, gate in scheduled)


async def test_disable_drains_its_request_and_refuses_only_its_own_work(harness, monkeypatch):
    app, manager = harness
    plugin, entered, finish = slow_plugin('slow-plugin')
    other, _, _ = slow_plugin('bystander')
    await manager.enable(plugin, package(monkeypatch, plugin))
    await manager.enable(other, package(monkeypatch, other))
    async with client_for(app) as client:
        request = asyncio.create_task(client.post('/api/v1/slow-plugin'))
        await entered.wait()
        disabling = asyncio.create_task(manager.disable(plugin))
        await asyncio.sleep(0)
        assert not disabling.done()
        refused = await client.get('/api/v1/slow-plugin')
        assert refused.status_code == 503 and refused.headers['Retry-After']
        # No 503 outside the changing plugin: another plugin and unowned routes serve.
        assert (await client.get('/api/v1/bystander')).json() == {'plugin': 'bystander'}
        assert (await client.get('/unrelated')).status_code == 200
        finish.set()
        assert (await request).json() == {'committed': True}
        await disabling
    assert plugin.id not in registries.plugins
    assert not admission.gate.counts


async def test_toggle_completes_while_another_plugins_long_request_is_in_flight(harness, monkeypatch):
    """The drain was process-global: one long import made every toggle time out."""
    app, manager = harness
    admission.gate.drain_timeout = 1
    importer, entered, finish = slow_plugin('long-import')
    toggled, _, _ = slow_plugin('toggled')
    await manager.enable(importer, package(monkeypatch, importer))
    path = package(monkeypatch, toggled)
    await manager.enable(toggled, path)
    async with client_for(app) as client:
        request = asyncio.create_task(client.post('/api/v1/long-import'))
        await entered.wait()
        assert admission.gate.counts == {importer.id: 1}
        await asyncio.wait_for(manager.disable(toggled), .5)
        await asyncio.wait_for(manager.enable(toggled, path), .5)
        assert (await client.get('/api/v1/toggled')).json() == {'plugin': 'toggled'}
        assert not request.done()
        finish.set()
        assert (await request).json() == {'committed': True}
    assert not admission.gate.counts


async def test_a_changing_plugin_pauses_only_its_own_loops(harness, monkeypatch):
    _, manager = harness
    ticks = []
    changing, steady = ticking_plugin('changing-loop', ticks), ticking_plugin('steady-loop', ticks)
    await manager.enable(changing, package(monkeypatch, changing))
    await manager.enable(steady, package(monkeypatch, steady))
    await asyncio.sleep(.03)
    assert {'changing-loop', 'steady-loop'} <= set(ticks)
    admission.gate.close(changing.id)  # what a pending disable holds
    await asyncio.sleep(.01)
    ticks.clear()
    await asyncio.sleep(.03)
    assert 'steady-loop' in ticks and 'changing-loop' not in ticks
    admission.gate.open(changing.id)
    await asyncio.sleep(.03)
    assert 'changing-loop' in ticks
    await manager.shutdown()


async def test_nothing_of_the_plugin_is_admitted_during_its_shutdown(harness, monkeypatch):
    """`exclusive` was set without a re-check: work admitted between the drain and
    the swap ran alongside on_shutdown. Admissions now close BEFORE the drain."""
    app, manager = harness
    attempts = []
    async def shutdown_hook():
        for _ in range(3):
            async with client_for(app) as client:
                attempts.append((await client.get('/api/v1/exclusive')).status_code)
            assert not admission.gate.counts.get(plugin.id)
    plugin, _, _ = slow_plugin('exclusive')
    plugin = RaddPlugin(name='exclusive', core=False, routers=plugin.routers, on_shutdown=(shutdown_hook,))
    await manager.enable(plugin, package(monkeypatch, plugin))
    await manager.disable(plugin)
    assert attempts == [503, 503, 503]


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
    assert plugin.id not in admission.gate.closed
    stop.assert_awaited_once()
    async with client_for(app) as client:
        assert 'fallback' in (await client.get('/api/v1/broken-plugin')).json()


async def test_spawned_job_is_drained_under_its_owner(harness):
    entered, finish = asyncio.Event(), asyncio.Event()
    async def job():
        entered.set()
        await finish.wait()
    token = admission.owner.set('fixture')
    task = runtime.spawn(job())
    admission.owner.reset(token)
    await entered.wait()
    assert admission.gate.counts == {'fixture': 1}
    admission.gate.close('fixture')
    draining = asyncio.create_task(admission.gate.drain('fixture'))
    await asyncio.sleep(.02)
    assert not draining.done()
    await asyncio.wait_for(admission.gate.drain('other-owner'), .1)  # nothing of its own
    finish.set()
    await task
    await asyncio.wait_for(draining, .1)


async def test_cancelled_before_start_job_releases_admission(harness):
    task = runtime.spawn(asyncio.sleep(100))
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert not admission.gate.counts


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


async def test_drain_timeout_never_cancels_running_work_and_stays_closed(harness):
    admission.gate.drain_timeout = .01
    finish = asyncio.Event()
    token = admission.owner.set('busy')
    job = runtime.spawn(finish.wait())
    admission.owner.reset(token)
    admission.gate.close('busy')
    with pytest.raises(admission.DrainTimeout) as timed_out:
        await admission.gate.drain('busy')
    assert timed_out.value.in_flight == 1
    assert not job.done()
    # A pending disable keeps its plugin closed: reopening between retries would
    # admit the very work that keeps the drain from finishing.
    assert 'busy' in admission.gate.closed
    finish.set()
    await job


async def test_shutdown_failure_remains_visible_and_retryable(harness, monkeypatch):
    _, manager = harness
    stop = AsyncMock(side_effect=RuntimeError('not stopped'))
    plugin = RaddPlugin(name='failed-stop', core=False, on_shutdown=(stop,))
    await manager.enable(plugin, package(monkeypatch, plugin))
    with pytest.raises(RuntimeError, match='not stopped'):
        await manager.disable(plugin)
    assert plugin.id in registries.plugins and plugin.id in admission.gate.closed
    stop.side_effect = None
    await manager.disable(plugin)
    assert plugin.id not in registries.plugins


async def test_resume_after_a_failed_shutdown_restarts_the_plugin(harness, monkeypatch):
    _, manager = harness
    start = AsyncMock()
    plugin = RaddPlugin(name='cancelled-stop', core=False, on_startup=(start,),
                        on_shutdown=(AsyncMock(side_effect=RuntimeError('half stopped')),))
    await manager.enable(plugin, package(monkeypatch, plugin))
    with pytest.raises(RuntimeError):
        await manager.disable(plugin)
    plugin.on_shutdown[0].side_effect = None
    await manager.resume(plugin)
    assert start.await_count == 2 and plugin.id not in admission.gate.closed


async def test_process_shutdown_runs_every_plugins_hooks_despite_one_failure(harness, monkeypatch):
    _, manager = harness
    flush = AsyncMock()
    first = RaddPlugin(name='flushes', core=False, on_shutdown=(flush,))
    second = RaddPlugin(name='fails-to-stop', core=False,
                        on_shutdown=(AsyncMock(side_effect=RuntimeError('boom')),))
    await manager.enable(first, package(monkeypatch, first))
    await manager.enable(second, package(monkeypatch, second))
    await manager.shutdown()  # the failing plugin stops first (reverse order)
    flush.assert_awaited_once()


async def test_lapsed_lease_refuses_only_non_core_plugin_work(harness, monkeypatch):
    """A lapsed lease used to 503 the whole process, the restore status included."""
    app, manager = harness
    optional, _, _ = slow_plugin('optional-plugin')
    core_router = APIRouter()
    @core_router.get('/backups/status')
    async def status():
        return {'restoring': True}
    core = RaddPlugin(name='backup-fixture', routers=(core_router,))
    await manager.enable(optional, package(monkeypatch, optional))
    await manager.enable(core, package(monkeypatch, core))
    admission.gate.renew(0)
    assert admission.gate.lease_state() is admission.LeaseState.LAPSED
    async with client_for(app) as client:
        refused = await client.get('/api/v1/optional-plugin')
        assert refused.status_code == 503 and 'unconfirmed' in refused.json()['detail']
        assert (await client.get('/api/v1/backups/status')).json() == {'restoring': True}
        assert (await client.get('/unrelated')).status_code == 200
    token = admission.owner.set(optional.id)
    try:
        ticking = asyncio.create_task(admission.gate.work().__aenter__())
        await asyncio.sleep(.01)
        assert not ticking.done()  # waits for the lease, never fails
        admission.gate.renew(None)
        await asyncio.wait_for(ticking, .1)
    finally:
        admission.owner.reset(token)


async def test_lapsed_lease_ends_only_non_core_plugin_sockets(harness):
    registries.register_plugin(RaddPlugin(name='socket-optional', core=False))
    registries.register_plugin(RaddPlugin(name='socket-core'))
    for owner_id, closed in (('socket-optional', True), ('socket-core', False)):
        received, messages = [], []
        async def app(scope, receive, send, owner_id=owner_id):
            scope[admission.ADMITTED_KEY].append(owner_id)  # what admission() records
            received.append(await receive())
        async def send(message):
            messages.append(message)
        async def receive():
            admission.gate.renew(0)  # lapses while the socket waits for its next message
            return {'type': 'websocket.receive', 'text': 'new work'}
        await runtime.RuntimeMiddleware(app)({'type': 'websocket'}, receive, send)
        if closed:
            assert received == [{'type': 'websocket.disconnect', 'code': 1013}]
            assert messages == [{'type': 'websocket.close', 'code': 1013}]
        else:
            assert received == [{'type': 'websocket.receive', 'text': 'new work'}] and not messages


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
    await queue.put({'type': 'websocket.connect'})
    messages = []
    async def send(message):
        messages.append(message)
    scope = {'type': 'websocket', 'asgi': {'version': '3.0'}, 'path': '/api/v1/live-socket',
             'root_path': '', 'scheme': 'ws', 'headers': [], 'query_string': b'',
             'server': ('test', 80), 'client': ('test', 1), 'subprotocols': []}
    connection = asyncio.create_task(app(scope, queue.get, send))
    await asyncio.wait_for(connected.wait(), 2)
    assert not admission.gate.counts  # a socket is closed on disable, never drained
    await manager.disable(plugin)
    await asyncio.gather(connection, return_exceptions=True)
    assert {'type': 'websocket.close', 'code': 1012} in messages
    flush.assert_awaited_once()
    assert not admission.gate.sockets
