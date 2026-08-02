"""The ldap module's first table (spec 85): one row per directory sync kind
recording when it last ran and what it did — served by GET /ldap/sync-status."""

from datetime import datetime
from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base


class DirectorySyncState(Base):
    """Last-run record for one periodic directory sync (spec 85). `kind` is a
    SyncKind value; `last_result` is the run's summary payload — user_sync:
    {provisioned, updated, deactivated, errors}, group_sync: {teams, added,
    removed, errors}."""

    __tablename__ = "directory_sync_state"

    kind: Mapped[str] = mapped_column(String(20), primary_key=True)  # SyncKind
    last_run_at: Mapped[datetime] = mapped_column()
    last_result: Mapped[dict[str, Any]] = mapped_column(JSONB)
