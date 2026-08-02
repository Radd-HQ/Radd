"""Integration sockets (spec 93 / A8, docs/plugin-platform.md §4a/§6).

The socket registry + interfaces let a plugin *provide* an implementation another
consumes. StorageBackend (filesystem/s3) and TaskBackend (localloop) already have
real providers registered via their plugins' manifests.
"""

from radd.kernel import sockets
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
