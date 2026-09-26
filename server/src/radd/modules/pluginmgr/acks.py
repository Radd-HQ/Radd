"""Process acknowledgements: ONE channel, the `plugin_processes` table (RADD-1372).

Every web/worker process upserts its own row on a heartbeat: which plugins it
runs, which desired-state versions it has observed, what it is still applying
and what failed. Writing the row renews the process's LEASE; a process whose
heartbeat cannot land for `plugin_lease_seconds` stops admitting non-core
plugin work (`kernel.admission`). Readers treat a row older than
`plugin_process_stale_seconds` as stale and disregard it, which is sound only
because the lease is shorter: by then the process has already stopped admitting.

The admin UI (`service.list_plugins`), Forget (`service.uninstall`) and package
removal (`ensure_unused`) all read these rows. There is no second channel: the
filesystem reports under `<plugins_dir>/runtime/` that RADD-1341 kept beside
the table are gone.
"""

import logging
import os
import socket
import time
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from radd.config import settings
from radd.db import SessionLocal
from radd.kernel import admission, registries

from . import store
from .models import PluginProcess

logger = logging.getLogger(__name__)

#: The observed version of a plugin with no `installed_plugins` row.
BOOTSTRAP_VERSION = "bootstrap"


def new_process_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def state_version(row) -> str:
    """The desired-state version a process acknowledges having observed."""
    return f"{row.state}:{getattr(row, 'updated_at', '')}" if row is not None else BOOTSTRAP_VERSION


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def cluster_reports(session) -> list[dict]:
    now = _utcnow()
    stale = timedelta(seconds=settings.plugin_process_stale_seconds)
    rows = (await session.execute(select(PluginProcess))).scalars()
    return [{**row.report, "stale": now - row.updated_at > stale} for row in rows]


def unconfirmed(peers: Iterable[dict], plugin_id: str, version: str) -> list[str]:
    """Live processes that may still run `plugin_id`, failed to apply it, or have
    not yet observed its current desired-state `version`."""
    return [
        peer.get("process", "?") for peer in peers
        if not peer.get("stale") and (
            plugin_id in peer.get("active", ()) or plugin_id in peer.get("pending", ())
            or plugin_id in (peer.get("errors") or {})
            or (peer.get("versions") or {}).get(plugin_id, BOOTSTRAP_VERSION) != version
        )
    ]


async def ensure_unused(session, plugin_id: str) -> None:
    """Package files may be removed only once every live process has observed the
    forgotten plugin (no row: BOOTSTRAP_VERSION) and runs none of it. The caller
    has already checked that the row is gone, so no process will load it again."""
    if plugin_id in registries.plugins:
        raise store.PackageError("Package is active in this process")
    peers = [peer for peer in await cluster_reports(session) if not peer["stale"]]
    if not peers:
        raise store.PackageError("No process acknowledgements yet; wait for plugin reconciliation")
    blockers = unconfirmed(peers, plugin_id, BOOTSTRAP_VERSION)
    if blockers:
        raise store.PackageError(
            "Package is active or unconfirmed on processes: " + ", ".join(blockers)
        )


async def publish(process_id: str, report: dict) -> None:
    """Upsert this process's row, prune long-gone processes, and renew the lease
    from the moment the write STARTED (a slow commit must not stretch it)."""
    started = time.monotonic()
    now = _utcnow()
    record = {**report, "process": process_id, "updated_at": time.time()}
    async with SessionLocal() as session:
        statement = insert(PluginProcess).values(process_id=process_id, report=record, updated_at=now)
        await session.execute(statement.on_conflict_do_update(
            index_elements=["process_id"], set_={"report": record, "updated_at": now}))
        retention = timedelta(hours=settings.plugin_process_retention_hours)
        await session.execute(delete(PluginProcess).where(PluginProcess.updated_at < now - retention))
        await session.commit()
    admission.gate.renew(started + settings.plugin_lease_seconds)


async def withdraw(process_id: str) -> None:
    """Delete this process's row at shutdown; its lease ends with it. Logged,
    never raised: a failure here must not cost another shutdown step."""
    admission.gate.renew(None)
    try:
        async with SessionLocal() as session:
            await session.execute(delete(PluginProcess).where(PluginProcess.process_id == process_id))
            await session.commit()
    except Exception:
        logger.exception("Could not withdraw plugin acknowledgement %s; it expires as stale", process_id)
