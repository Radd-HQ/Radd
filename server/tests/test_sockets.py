"""Integration sockets (spec 93 / A8, docs/plugin-platform.md §4a/§6).

The socket registry + interfaces let a plugin *provide* an implementation another
consumes. StorageBackend (filesystem/s3) and TaskBackend (localloop) already have
real providers registered via their plugins' manifests.
"""

from functools import partial

import pytest

from radd.kernel import ContributionConflict, IntegrationSpec, RaddPlugin, register_integration, sockets
from radd.kernel.registry import registries
from radd.kernel.sockets import Socket, StorageBackend, TaskBackend
from radd.modules.attachments.models import StorageHost
from radd.modules.attachments.types import StorageHostType


def test_storage_backend_providers_registered():
    provs = sockets.providers(Socket.STORAGE_BACKEND)
    assert set(provs) == {"filesystem", "s3"}


def test_storage_backend_impls_are_per_host_client_factories():
    """Spec 102: the registered impl is a class taking a StorageHost row; the
    instance conforms to the StorageBackend Protocol (the request-path seam)."""
    factory = sockets.provider(Socket.STORAGE_BACKEND, "filesystem")
    host = StorageHost(
        name="probe", host_type=StorageHostType.FILESYSTEM.value, root_dir="/tmp/probe"
    )
    assert isinstance(factory(host), StorageBackend)


def test_task_backend_localloop_registered():
    localloop = sockets.provider(Socket.TASK_BACKEND, "localloop")
    assert localloop is not None
    assert isinstance(localloop, TaskBackend)
    # the socket is the swap point for a celery plugin
    assert "localloop" in sockets.providers(Socket.TASK_BACKEND)


def test_unknown_provider_is_none():
    assert sockets.provider(Socket.TASK_BACKEND, "celery") is None


# --- RADD-1456: one provider per key, a declared policy per socket ---


def _providing(name: str, socket: Socket, key: str) -> RaddPlugin:
    return RaddPlugin(
        name=name, core=False, integrations=(IntegrationSpec(socket, key, impl=object()),)
    )


def test_every_socket_declares_what_happens_without_a_provider():
    assert set(sockets.SOCKET_POLICIES) == set(Socket)
    assert sockets.socket_policy(Socket.TRANSITION_CHECK).fails_closed
    assert sockets.socket_policy(Socket.MAIL_TRANSPORT) == sockets.SocketPolicy(fails_closed=True, single=True)
    assert not sockets.socket_policy(Socket.PERSON_AVAILABILITY).fails_closed
    # A socket a plugin defines for itself (vcs's connector tabs) is open and multi.
    assert sockets.socket_policy("acme.tabs") == sockets.PLUGIN_SOCKET_POLICY


def test_two_plugins_on_one_integration_key_conflict_and_nothing_is_overwritten():
    first = _providing("first-docs", Socket.SEARCH_DOCUMENTS, "shared-corpus")
    second = _providing("second-docs", Socket.SEARCH_DOCUMENTS, "shared-corpus")
    registries.register_plugin(first)
    try:
        with pytest.raises(ContributionConflict, match="'first-docs' and 'second-docs'"):
            registries.register_plugin(second)
        assert second.id not in registries.plugins, "a refused plugin registers nothing"
        assert sockets.provider(Socket.SEARCH_DOCUMENTS, "shared-corpus") is first.integrations[0].impl
        registries.register_plugin(first)  # its own key again (a reload) is no conflict
        # An import-time registration is refused the same way, and never replaces.
        with pytest.raises(ContributionConflict, match="first-docs"):
            register_integration(IntegrationSpec(Socket.SEARCH_DOCUMENTS, "shared-corpus", impl=object()))
    finally:
        registries.unregister_plugin(first)
    assert sockets.provider(Socket.SEARCH_DOCUMENTS, "shared-corpus") is None
    assert (Socket.SEARCH_DOCUMENTS.value, "shared-corpus") not in registries.integration_owners


async def test_a_conflicting_enable_is_reported_on_its_row_naming_both(monkeypatch):
    from radd.modules.pluginmgr import live

    monkeypatch.setattr(live, "_runtime", None)  # the declarations-only apply path
    for name, empty in (("_errors", {}), ("_backoff", {}), ("_pending", set())):
        monkeypatch.setattr(live, name, empty)
    first = _providing("row-first", Socket.SEARCH_DOCUMENTS, "row-corpus")
    second = _providing("row-second", Socket.SEARCH_DOCUMENTS, "row-corpus")
    registries.register_plugin(first)
    try:
        await live._attempt(second.id, True, partial(live._enable, second, "unused.path"))
        message = live._errors[second.id]
        assert "row-first" in message and "row-second" in message and "ContributionConflict" in message
        assert second.id not in registries.plugins
    finally:
        registries.unregister_plugin(first)


def test_a_single_provider_socket_admits_one_plugin_and_the_reader_refuses_two():
    from radd.modules.mailintake import plugin as mailintake_plugin

    one = _providing("mail-one", Socket.MAIL_TRANSPORT, "one")
    other = _providing("mail-other", Socket.MAIL_TRANSPORT, "other")
    registries.unregister_plugin(mailintake_plugin)
    try:
        registries.register_plugin(one)
        try:
            assert sockets.single_provider(Socket.MAIL_TRANSPORT) is one.integrations[0].impl
            with pytest.raises(ContributionConflict, match="'mail-one'.*'mail-other'"):
                registries.register_plugin(other)
            # Past the registry (a direct write), the reader still refuses to pick one.
            registries.integrations[(Socket.MAIL_TRANSPORT.value, "other")] = other.integrations[0]
            try:
                with pytest.raises(sockets.AmbiguousProvider, match="one, other"):
                    sockets.single_provider(Socket.MAIL_TRANSPORT)
            finally:
                registries.integrations.pop((Socket.MAIL_TRANSPORT.value, "other"))
        finally:
            registries.unregister_plugin(one)
        assert sockets.single_provider(Socket.MAIL_TRANSPORT) is None
    finally:
        registries.register_plugin(mailintake_plugin)


def test_a_transition_check_provider_answers_only_for_its_registered_key():
    from radd.modules.workflow import checks

    class Impostor:
        check = "somebody_elses_check"
        sort_last = False

    live_before = checks.providers()
    assert all(impl.check == key for key, impl in live_before.items())
    register_integration(IntegrationSpec(Socket.TRANSITION_CHECK, "declared_key", impl=Impostor()))
    try:
        with pytest.raises(ValueError, match="'declared_key' answers for 'somebody_elses_check'"):
            checks.providers()
    finally:
        registries.integrations.pop((Socket.TRANSITION_CHECK.value, "declared_key"))
    assert checks.providers() == live_before
