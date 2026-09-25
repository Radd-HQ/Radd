import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class AlertReceiver(Base, TimestampMixin):
    """One Alertmanager webhook receiver (RADD-1317): its token and the project
    its alerts become issues in. Rows, not env vars — `RADD_ALERTMANAGER_TOKEN` +
    `_PROJECT_KEY` seed one, once."""

    __tablename__ = "alertmanager_receivers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    token: Mapped[str] = mapped_column(String(200))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AlertItem(Base):
    """Alert fingerprint → issue dedup map (spec 47): one issue per Alertmanager
    fingerprint, instance-wide; repeats and resolutions are trigger events on it.
    `receiver_id` records which receiver first saw it (RADD-1317)."""

    __tablename__ = "alert_items"

    fingerprint: Mapped[str] = mapped_column(Text, primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"))
    receiver_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alertmanager_receivers.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
