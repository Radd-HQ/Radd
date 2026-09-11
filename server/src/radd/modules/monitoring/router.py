from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.models import User
from radd.modules.events import service as events_service

from . import service
from .schemas import DatabaseHealth, EntityCount, MonitoringOverview, WorkerStatus

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

Session = Annotated[AsyncSession, Depends(get_session)]

# What the counts card shows: (table, key, label). Read via pg_stat_user_tables
# (live-tuple ESTIMATES — instant at any corpus size), never by querying other
# modules' tables directly: catalog metadata is infrastructure, not module data.
_COUNTED_TABLES: tuple[tuple[str, str, str], ...] = (
    ("projects", "projects", "Projects"),
    ("work_items", "items", "Issues"),
    ("users", "users", "Users"),
    ("comments", "comments", "Comments"),
    ("worklogs", "worklogs", "Worklogs"),
    ("pages", "pages", "Wiki pages"),
    ("attachments", "attachments", "Attachments"),
    ("events", "events", "Events"),
    ("search_index", "search_index", "Search index rows"),
)


def _require_instance_admin(actor: User) -> None:
    if not authz.is_instance_admin(actor):
        raise ForbiddenError("monitoring requires an instance admin")


@router.get("/overview", response_model=MonitoringOverview)
async def overview(session: Session, user: CurrentUser) -> MonitoringOverview:
    """One glance for operators: DB health, entity counts, and each background
    consumer's cursor lag (Settings → Monitoring polls this)."""
    _require_instance_admin(user)

    version_row = await session.execute(text("SHOW server_version"))
    size_row = await session.execute(text("SELECT pg_database_size(current_database())"))
    connections_row = await session.execute(
        text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
    )
    database = DatabaseHealth(
        ok=True,  # this handler answered, so the DB round-trip succeeded
        postgres_version=str(version_row.scalar() or ""),
        size_bytes=int(size_row.scalar() or 0),
        active_connections=int(connections_row.scalar() or 0),
    )

    counted = await session.execute(
        text(
            "SELECT relname, n_live_tup FROM pg_stat_user_tables WHERE relname = ANY(:names)"
        ),
        {"names": [table for table, _key, _label in _COUNTED_TABLES]},
    )
    live = {relname: int(count) for relname, count in counted.all()}
    counts = [
        EntityCount(key=key, label=label, count=live.get(table, 0))
        for table, key, label in _COUNTED_TABLES
    ]

    workers = [WorkerStatus(**row) for row in await events_service.consumer_status(session)]

    return MonitoringOverview(
        database=database,
        counts=counts,
        workers=workers,
        workers_in_process=settings.run_workers,
        # RADD-1036: terminally-failed outbound mail, which until now existed
        # only as two events in a stream nobody aggregated.
        mail=await service.mail_health(session),
    )
