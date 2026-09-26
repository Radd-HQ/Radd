"""RADD-1341/1372: reconciliation, acknowledgements, attribution, consumer resume."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from radd.kernel import ConsumerResume, RaddPlugin, admission
from radd.modules.pluginmgr import acks, live, service
from radd.modules.pluginmgr.types import RuntimeState


def only_installable(monkeypatch, *plugins):
    monkeypatch.setattr('radd.modules.pluginmgr.discovery.core_plugins', lambda: {})
    monkeypatch.setattr('radd.modules.pluginmgr.discovery.installable_plugins',
                        lambda: {p.id: (p, 'fixture') for p in plugins})


def rows(state, *plugins, **extra):
    return {p.id: SimpleNamespace(state=state, version='1', **extra) for p in plugins}


async def test_peer_pending_and_error_not_misreported_as_disabled(monkeypatch):
    plugin = RaddPlugin(name='peer-plugin', core=False)
    only_installable(monkeypatch, plugin)
    monkeypatch.setattr(service, '_states', AsyncMock(return_value=rows('disabled', plugin)))
    peer = {'process': 'worker', 'active': [plugin.id], 'observed': [],
            'versions': {plugin.id: 'disabled:'}, 'stale': False}
    monkeypatch.setattr(acks, 'cluster_reports', AsyncMock(return_value=[peer]))
    row = (await service.list_plugins(AsyncMock()))[0]
    assert row.runtime_state == RuntimeState.APPLYING and row.pending_processes == 1
    peer['errors'] = {plugin.id: 'Shutdown failed'}
    row = (await service.list_plugins(AsyncMock()))[0]
    assert row.runtime_state == RuntimeState.ERROR and row.runtime_errors == ('Shutdown failed',)
    peer.update(active=[], errors={})
    assert (await service.list_plugins(AsyncMock()))[0].runtime_state == RuntimeState.DISABLED


async def test_a_process_error_is_not_charged_to_every_plugin(monkeypatch):
    """One peer's reconcile failure made every row read "Apply failed" and made
    uninstall refuse every plugin. It is reported once, on /plugins/runtime."""
    failing, bystander = RaddPlugin(name='failing', core=False), RaddPlugin(name='bystander', core=False)
    only_installable(monkeypatch, failing, bystander)
    monkeypatch.setattr(service, '_states', AsyncMock(return_value=rows('disabled', failing, bystander)))
    peer = {'process': 'worker', 'active': [], 'observed': [], 'stale': False,
            'versions': {failing.id: 'disabled:', bystander.id: 'disabled:'},
            'error': 'OperationalError: reconciliation failed',
            'errors': {failing.id: 'RuntimeError: disable failed; will retry'}}
    monkeypatch.setattr(acks, 'cluster_reports', AsyncMock(return_value=[peer]))
    infos = {i.id: i for i in await service.list_plugins(AsyncMock())}
    assert infos[bystander.id].runtime_state == RuntimeState.DISABLED
    assert not infos[bystander.id].runtime_errors and not infos[bystander.id].pending_processes
    assert infos[failing.id].runtime_state == RuntimeState.ERROR
    assert acks.unconfirmed([peer], bystander.id, 'disabled:') == []
    assert acks.unconfirmed([peer], failing.id, 'disabled:') == ['worker']
    # A peer that has not observed the current version still blocks Forget.
    assert acks.unconfirmed([peer], bystander.id, 'disabled:later') == ['worker']
    assert acks.unconfirmed([{**peer, 'stale': True, 'active': [bystander.id]}], bystander.id, 'x') == []


async def test_shared_database_requires_both_process_acknowledgements(monkeypatch):
    from datetime import UTC, datetime, timedelta
    from radd.db import SessionLocal
    from radd.modules.pluginmgr.models import PluginProcess
    plugin = RaddPlugin(name='two-replicas', core=False)
    only_installable(monkeypatch, plugin)
    monkeypatch.setattr(service, '_states', AsyncMock(return_value=rows('disabled', plugin)))
    async with SessionLocal() as session:
        now = datetime.now(UTC).replace(tzinfo=None)
        report = {'active': [], 'observed': [], 'versions': {plugin.id: 'disabled:'}}
        web = PluginProcess(process_id='test-web', updated_at=now, report={**report, 'process': 'test-web'})
        worker = PluginProcess(process_id='test-worker', updated_at=now,
                               report={**report, 'process': 'test-worker', 'active': [plugin.id]})
        session.add_all([web, worker])
        await session.flush()
        row = (await service.list_plugins(session))[0]
        assert row.runtime_state == RuntimeState.APPLYING and row.pending_processes == 1
        worker.report = {**worker.report, 'active': []}
        await session.flush()
        assert (await service.list_plugins(session))[0].runtime_state == RuntimeState.DISABLED
        worker.report = {**worker.report, 'active': [plugin.id]}
        worker.updated_at = now - timedelta(seconds=31)
        await session.flush()
        assert (await service.list_plugins(session))[0].runtime_state == RuntimeState.DISABLED
        assert next(r for r in await acks.cluster_reports(session) if r['process'] == 'test-worker')['stale']
        await session.rollback()


async def test_previous_toggle_ack_cannot_complete_a_new_request(monkeypatch):
    plugin = RaddPlugin(name='revision-check', core=False)
    only_installable(monkeypatch, plugin)
    row = SimpleNamespace(state='disabled', version='1', updated_at='new-request')
    monkeypatch.setattr(service, '_states', AsyncMock(return_value={plugin.id: row}))
    peer = {'active': [], 'observed': [], 'stale': False, 'versions': {plugin.id: 'disabled:previous-request'}}
    monkeypatch.setattr(acks, 'cluster_reports', AsyncMock(return_value=[peer]))
    assert (await service.list_plugins(AsyncMock()))[0].runtime_state == RuntimeState.APPLYING
    peer['versions'][plugin.id] = acks.state_version(row)
    assert (await service.list_plugins(AsyncMock()))[0].runtime_state == RuntimeState.DISABLED


@pytest.fixture
def fresh_reconciler(monkeypatch, tmp_path):
    monkeypatch.setattr('radd.modules.pluginmgr.store.settings.plugins_dir', str(tmp_path / 'plugins'))
    monkeypatch.setattr(live, '_runtime', None)
    monkeypatch.setattr(live, '_fingerprint', None)
    for name, empty in (('_errors', {}), ('_backoff', {}), ('_pending', set())):
        monkeypatch.setattr(live, name, empty)


async def test_unchanged_state_skips_discovery_and_a_failed_apply_backs_off(monkeypatch, fresh_reconciler):
    """Every 2 s every process re-ran discovery; failures retried at full rate."""
    discoveries = []
    # A backend plugin cannot be applied without a bound runtime: a stand-in for a failing enable.
    plugin = RaddPlugin(name='backoff-fixture', core=False, on_startup=(AsyncMock(),))
    monkeypatch.setattr('radd.modules.pluginmgr.discovery.core_plugins',
                        lambda: discoveries.append(1) or {})
    monkeypatch.setattr('radd.modules.pluginmgr.discovery.installable_plugins',
                        lambda: {plugin.id: (plugin, 'fixture')})
    monkeypatch.setattr(service, '_states', AsyncMock(return_value=rows('enabled', plugin)))
    assert await live.reconcile() is True
    assert 'enable failed' in live._errors[plugin.id]
    first = len(discoveries)
    assert await live.reconcile() is False  # nothing moved and the retry is not due
    assert len(discoveries) == first
    desired, _at, delay = live._backoff[plugin.id]
    live._backoff[plugin.id] = (desired, 0, delay)  # the retry falls due
    assert await live.reconcile() is True
    assert len(discoveries) > first
    assert live._backoff[plugin.id][2] == 2 * delay  # doubled
    # Cancelling the request (desired → disabled) settles it and clears the error.
    service._states.return_value = rows('disabled', plugin)
    assert await live.reconcile() is True
    assert plugin.id not in live._errors and plugin.id not in live._backoff


async def test_reenabled_head_consumer_skips_the_backlog(monkeypatch):
    """A disable→enable replayed every event since the disable through
    mailintake.outbound / csat.sender into requesters' inboxes."""
    from radd.db import SessionLocal
    from radd.modules.events import service as events
    from radd.modules.pluginmgr.models import InstalledPlugin
    from radd.modules.pluginmgr.types import PluginEntity, PluginEvent
    suffix = uuid.uuid4().hex[:8]
    head_name, cursor_name = f'fixture.mailer.{suffix}', f'fixture.index.{suffix}'
    plugin = RaddPlugin(name=f'resume-{suffix}', core=False, consumer_names=(head_name, cursor_name),
                        consumer_resume=((head_name, ConsumerResume.HEAD),))
    only_installable(monkeypatch, plugin)
    monkeypatch.setattr(acks, 'cluster_reports', AsyncMock(return_value=[]))
    async with SessionLocal() as session:
        before = await events.latest_event_id(session)
        for name in (head_name, cursor_name):
            await events.set_offset(session, name, before)
        session.add(InstalledPlugin(id=plugin.id, version='0', state='disabled', config={}))
        for _ in range(3):  # the instance kept working while the plugin was off
            await events.emit(session, event_type=PluginEvent.INSTALLED, entity_type=PluginEntity.PLUGIN,
                              entity_id=f'elsewhere-{suffix}', actor_id=None, payload={'id': suffix})
        await session.flush()
        backlog_end = await events.latest_event_id(session)
        assert backlog_end > before
        await service.enable(session, plugin.id)
        # Skips the backlog: resumes at the head as of the re-enable (the enable's
        # own plugin.enabled event follows it).
        assert await events.get_offset(session, head_name) == backlog_end
        assert await events.get_offset(session, cursor_name) == before  # an index catches up
        # Enabling what is already enabled is not a re-enable: it never skips.
        await events.set_offset(session, head_name, backlog_end)
        await service.enable(session, plugin.id)
        assert await events.get_offset(session, head_name) == backlog_end
        await session.rollback()
    with pytest.raises(ValueError, match='own consumers'):
        RaddPlugin(name='bad', consumer_resume=(('not.mine', ConsumerResume.HEAD),))


async def test_withdrawing_the_acknowledgement_never_raises(monkeypatch):
    """It ran first in the lifespan's finally and, raising, skipped every plugin's
    on_shutdown (collab's flush). It now runs last and only logs."""
    def unreachable():
        raise OSError('database gone')
    monkeypatch.setattr(acks, 'SessionLocal', unreachable)
    monkeypatch.setattr(admission, 'gate', admission.RuntimeGate())
    admission.gate.renew(10**12)
    await acks.withdraw('gone-process')
    assert admission.gate.lease_state() is admission.LeaseState.UNLEASED


async def test_health_reports_the_plugin_lease(monkeypatch):
    import httpx
    from radd.app import create_app
    monkeypatch.setattr(admission, 'gate', admission.RuntimeGate())
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        body = (await client.get('/health')).json()
        assert body['status'] == 'ok' and body['plugin_lease'] == 'unleased'
        admission.gate.renew(0)
        lapsed = await client.get('/health')
        assert lapsed.status_code == 200  # never restart a process for a DB outage
        assert lapsed.json()['status'] == 'degraded' and lapsed.json()['plugin_lease'] == 'lapsed'
