import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint, false, func
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class AlertReceiver(Base, TimestampMixin):
    """One Alertmanager webhook receiver (RADD-1317): its token and the project
    its alerts become issues in. Rows, not env vars — `RADD_ALERTMANAGER_TOKEN` +
    `_PROJECT_KEY` seed one, once. The token is compared, never hashed, so it is
    stored recoverably — as secretbox ciphertext (RADD-1446;
    `service.receiver_for_token` is the one place it is decrypted)."""

    __tablename__ = "alertmanager_receivers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    token: Mapped[str] = mapped_column(Text)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # RADD-1370: what a delivery does to the alert's issue beyond creating it and
    # firing triggers — each off/empty until set on Settings → Alertmanager.
    #: An internal comment when the alert fires again and when it resolves.
    comment_updates: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    #: A label every issue this receiver creates carries ("" = none).
    label: Mapped[str] = mapped_column(String(100), default="", server_default="")
    #: Where a resolved alert's issue moves — a state of the receiver's project.
    resolve_state_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("states.id", ondelete="SET NULL"), nullable=True, default=None
    )


class AlertItem(Base):
    """Deduplicate alerts within their receiver, never across monitoring sources."""

    __tablename__ = "alert_items"

    __table_args__ = (UniqueConstraint("receiver_id", "fingerprint", name="uq_alert_items_receiver_fingerprint"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    fingerprint: Mapped[str] = mapped_column(Text)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"))
    receiver_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alertmanager_receivers.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AlertSeed(Base):
    """Durable ownership marker; deleting receivers must not reset initial setup."""

    __tablename__ = "alertmanager_seed"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
