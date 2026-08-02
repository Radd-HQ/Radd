import uuid
from typing import Any

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class ScopedSetting(Base, TimestampMixin):
    """One overridden scalar setting at one scope (specs 50/67). Absence of a row =
    inherit the wider scope; the widest fallback is the env/config default.
    `scope_id` is the project_id, and NULL for the instance scope."""

    __tablename__ = "scoped_settings"
    __table_args__ = (UniqueConstraint("scope", "scope_id", "key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(20), index=True)  # SettingScope
    scope_id: Mapped[uuid.UUID | None] = mapped_column(index=True)  # NULL for instance
    key: Mapped[str] = mapped_column(String(64), index=True)  # SettingKey
    value: Mapped[Any] = mapped_column(JSONB)  # the scalar, typed per the registry
