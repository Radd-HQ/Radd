"""Directory sync-state bookkeeping (spec 85): both periodic loops (and the
on-demand user-sync endpoint) record their last run here; GET /ldap/sync-status
serves the rows. Flush-only — the calling loop/request owns the commit."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import security

from .models import DirectorySyncState
from .types import SyncKind


async def record_run(session: AsyncSession, kind: SyncKind, result: dict[str, Any]) -> None:
    """Upsert the `kind` row with now + the run's summary payload."""
    row = await session.get(DirectorySyncState, kind.value)
    if row is None:
        session.add(
            DirectorySyncState(kind=kind.value, last_run_at=security.utcnow(), last_result=result)
        )
    else:
        row.last_run_at = security.utcnow()
        row.last_result = result
    await session.flush()


async def all_states(session: AsyncSession) -> dict[str, DirectorySyncState]:
    """kind value → row (absent kinds simply have no row yet)."""
    rows = (await session.execute(select(DirectorySyncState))).scalars()
    return {row.kind: row for row in rows}
